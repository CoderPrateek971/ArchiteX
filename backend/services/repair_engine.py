import ast
import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from database import ledger
from services.repair_planner import (
    TestValidationRequest,
    TestValidationResult,
    validate_repair_with_tests,
)
from services.workspace_manager import get_workspace_root

logger = logging.getLogger(__name__)


class RepairApplyRequest(BaseModel):
    issue_id: str = Field(..., min_length=1, description="ID of the issue or finding being resolved")
    file_path: str = Field(..., min_length=1, description="Target file path relative to workspace root")
    severity: str = Field(..., description="Severity of the issue (only 'low' is eligible for automatic repair)")
    proposed_code: str = Field(..., description="New Python source code proposed as the fix")
    workspace_root: Optional[str] = Field(None, description="Absolute or relative path to the workspace root directory")
    workspace_id: Optional[str] = Field(None, description="Workspace identifier if managed by workspace_manager")
    approval: bool = Field(False, description="Explicit human or system approval to apply this automatic repair")
    original_code_hash: Optional[str] = Field(None, description="SHA-256 hash of original file code for concurrency check")
    expected_original_code: Optional[str] = Field(None, description="Exact expected original code for concurrency verification")


class RepairApplyResult(BaseModel):
    success: bool
    issue_id: str
    file_path: str
    severity: str
    validation_status: str  # "PASSED", "FAILED", "REJECTED", "BLOCKED", "CONFLICT"
    output_logs: str
    rollback_status: str    # "NOT_NEEDED", "RESTORED", "NOT_APPLICABLE"
    explanation: str
    change_id: Optional[int] = None
    details: list[dict[str, Any]] = Field(default_factory=list)


def _normalize_code(code: str) -> str:
    """Normalize line endings and whitespace for cross-platform comparison."""
    if not code:
        return ""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def _compute_hash(code: str) -> str:
    return hashlib.sha256(_normalize_code(code).encode("utf-8")).hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _atomic_write(target_path: Path, content: str) -> None:
    """Safely write code using an atomic rename operation."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.parent / f".tmp_{target_path.name}_{uuid.uuid4().hex}"
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(target_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def apply_automatic_repair(
    issue_id: str,
    file_path: str,
    severity: str,
    proposed_code: str,
    workspace_root: Optional[str] = None,
    workspace_id: Optional[str] = None,
    approval: bool = False,
    original_code_hash: Optional[str] = None,
    expected_original_code: Optional[str] = None,
) -> RepairApplyResult:
    """
    Executes an automated code repair under strict safety, security, and verification guarantees.

    Guarantees:
    1. Approval Gate: Explicit approval flag is strictly required.
    2. Severity Policy: Automatic repair is ONLY allowed for LOW severity issues; Medium and High are rejected.
    3. Workspace Boundary: Blocks path traversal and unsafe paths outside the designated workspace.
    4. Concurrency Guard: Detects if the original file changed since the proposed fix was generated.
    5. Reversible Execution: Preserves original source; automatically rolls back upon syntax or test failures.
    6. Safety: Does not execute arbitrary shell commands supplied by the proposed fix.
    7. Ledger Audit: Records all successful or failed repair attempts in the persistent audit ledger.
    """
    clean_path = file_path.replace("file:", "").strip()
    sev_normalized = str(severity).strip().lower()

    # 1. Gate: Explicit human or system approval
    if not approval:
        return RepairApplyResult(
            success=False,
            issue_id=issue_id,
            file_path=clean_path,
            severity=severity,
            validation_status="REJECTED",
            output_logs="",
            rollback_status="NOT_APPLICABLE",
            explanation="Automatic repair rejected: Explicit approval is required before applying automated code changes.",
        )

    # 2. Gate: Severity restriction (Only LOW severity fixes are eligible for automated application)
    if sev_normalized != "low":
        return RepairApplyResult(
            success=False,
            issue_id=issue_id,
            file_path=clean_path,
            severity=severity,
            validation_status="REJECTED",
            output_logs="",
            rollback_status="NOT_APPLICABLE",
            explanation=(
                f"Automatic repair rejected: Automatic application is strictly restricted to LOW severity fixes. "
                f"'{severity}' severity issues require guided developer review and manual verification."
            ),
        )

    # 3. Resolve and validate workspace boundary
    try:
        if workspace_id and not workspace_root:
            root = get_workspace_root(workspace_id)
        elif workspace_root:
            root = Path(workspace_root).resolve()
        else:
            root = Path(os.getenv("ARCHITEX_WORKSPACE", Path.cwd())).resolve()

        if not root.exists():
            root.mkdir(parents=True, exist_ok=True)

        target_file = Path(clean_path).expanduser()
        if target_file.is_absolute():
            resolved_target = target_file.resolve()
        else:
            resolved_target = (root / target_file).resolve()

        if not _is_relative_to(resolved_target, root):
            return RepairApplyResult(
                success=False,
                issue_id=issue_id,
                file_path=clean_path,
                severity=severity,
                validation_status="BLOCKED",
                output_logs="",
                rollback_status="NOT_APPLICABLE",
                explanation=f"Security violation: Target file '{clean_path}' is outside workspace '{root}'. Path traversal blocked.",
            )
    except Exception as exc:
        return RepairApplyResult(
            success=False,
            issue_id=issue_id,
            file_path=clean_path,
            severity=severity,
            validation_status="BLOCKED",
            output_logs="",
            rollback_status="NOT_APPLICABLE",
            explanation=f"Workspace path resolution failed: {exc}",
        )

    # 4. Check file existence and read original source
    if not resolved_target.is_file():
        return RepairApplyResult(
            success=False,
            issue_id=issue_id,
            file_path=clean_path,
            severity=severity,
            validation_status="NOT_FOUND",
            output_logs="",
            rollback_status="NOT_APPLICABLE",
            explanation=f"Target file does not exist on disk: {resolved_target}",
        )

    original_code = resolved_target.read_text(encoding="utf-8", errors="replace")

    # 5. Concurrency Check: ensure original file has not changed since fix was generated
    if original_code_hash:
        current_hash = _compute_hash(original_code)
        if current_hash != original_code_hash:
            return RepairApplyResult(
                success=False,
                issue_id=issue_id,
                file_path=clean_path,
                severity=severity,
                validation_status="CONFLICT",
                output_logs="",
                rollback_status="NOT_APPLICABLE",
                explanation=(
                    f"Concurrency conflict: Target file '{clean_path}' has been modified since the proposed fix was generated. "
                    f"Expected hash {original_code_hash[:12]}… but found {current_hash[:12]}… Automatic repair aborted."
                ),
            )

    if expected_original_code is not None:
        if _normalize_code(original_code) != _normalize_code(expected_original_code):
            return RepairApplyResult(
                success=False,
                issue_id=issue_id,
                file_path=clean_path,
                severity=severity,
                validation_status="CONFLICT",
                output_logs="",
                rollback_status="NOT_APPLICABLE",
                explanation="Concurrency conflict: Current file contents differ from expected base code. Repair aborted.",
            )

    # 6. Pre-flight static Python AST validation
    try:
        ast.parse(proposed_code, filename=str(resolved_target))
    except SyntaxError as syn_err:
        # Record failed repair attempt in ledger
        entry = ledger.insert_log(
            file_path=str(resolved_target),
            previous_code=original_code,
            new_code=proposed_code,
            severity=severity,
            changed_by=ledger.ChangedBy.AI,
            details=f"Automatic repair for issue {issue_id} rejected due to syntax error: {syn_err.msg} (Line {syn_err.lineno})",
            issue_id=issue_id,
            validation_result=f"FAILED: SyntaxError at line {syn_err.lineno}: {syn_err.msg}",
            status=ledger.LedgerStatus.FAILED,
            workspace_root=str(root),
        )
        return RepairApplyResult(
            success=False,
            issue_id=issue_id,
            file_path=clean_path,
            severity=severity,
            validation_status="FAILED",
            output_logs=f"SyntaxError in proposed code (Line {syn_err.lineno}): {syn_err.msg}",
            rollback_status="RESTORED",
            explanation=f"Automatic repair rejected: Proposed code contains SyntaxError at line {syn_err.lineno}: {syn_err.msg}. Original file unchanged.",
            change_id=entry.id,
        )

    # 7. Apply proposed code safely with atomic write
    try:
        _atomic_write(resolved_target, proposed_code)
    except Exception as exc:
        return RepairApplyResult(
            success=False,
            issue_id=issue_id,
            file_path=clean_path,
            severity=severity,
            validation_status="FAILED",
            output_logs="",
            rollback_status="NOT_APPLICABLE",
            explanation=f"Failed to write proposed code atomically to disk: {exc}",
        )

    # 8. Reusable Test & Regression Validation Engine (Module 5 integration)
    rel_file = str(resolved_target.relative_to(root))
    val_request = TestValidationRequest(
        files_to_validate=[rel_file],
        workspace_root=str(root),
        code_overrides={},
        run_pytest=True,
    )
    val_result: TestValidationResult = validate_repair_with_tests(val_request)

    # Check whether a regression test suite exists in this workspace
    test_dir = root / "tests"
    has_test_suite = test_dir.exists() or any(
        f.name.startswith("test_") or f.name.endswith("_test.py")
        for f in root.rglob("*.py")
    )

    # Determine overall pass status
    # If a test suite exists, tests MUST pass. If no test suite exists, syntax compilation must pass.
    if has_test_suite:
        validation_passed = val_result.passed and val_result.syntax_passed and val_result.tests_passed
    else:
        validation_passed = val_result.syntax_passed

    if not validation_passed:
        # 9. Validation failed: Automatically restore original source code
        _atomic_write(resolved_target, original_code)

        # Record failed repair in ledger
        entry = ledger.insert_log(
            file_path=str(resolved_target),
            previous_code=original_code,
            new_code=proposed_code,
            severity=severity,
            changed_by=ledger.ChangedBy.AI,
            details=f"Automatic repair for issue {issue_id} failed verification test suite.",
            issue_id=issue_id,
            validation_result=val_result.output_log[:1000],
            status=ledger.LedgerStatus.FAILED,
            workspace_root=str(root),
        )

        return RepairApplyResult(
            success=False,
            issue_id=issue_id,
            file_path=clean_path,
            severity=severity,
            validation_status="FAILED",
            output_logs=val_result.output_log,
            rollback_status="RESTORED",
            explanation="Automatic repair failed validation tests. Original file was automatically restored.",
            change_id=entry.id,
            details=val_result.details,
        )

    # 10. Validation succeeded: record change in the ledger
    entry = ledger.insert_log(
        file_path=str(resolved_target),
        previous_code=original_code,
        new_code=proposed_code,
        severity=severity,
        changed_by=ledger.ChangedBy.AI,
        details=f"Automatic repair successfully applied for issue {issue_id}",
        issue_id=issue_id,
        validation_result="PASSED",
        status=ledger.LedgerStatus.ACTIVE,
        workspace_root=str(root),
    )

    return RepairApplyResult(
        success=True,
        issue_id=issue_id,
        file_path=clean_path,
        severity=severity,
        validation_status="PASSED",
        output_logs=val_result.output_log,
        rollback_status="NOT_NEEDED",
        explanation=f"Automatic repair for issue {issue_id} successfully applied, validated, and recorded in Smart Ledger (Change #{entry.id}).",
        change_id=entry.id,
        details=val_result.details,
    )


def apply_repair_request(request: RepairApplyRequest) -> RepairApplyResult:
    """Convenience wrapper accepting a RepairApplyRequest Pydantic object."""
    return apply_automatic_repair(
        issue_id=request.issue_id,
        file_path=request.file_path,
        severity=request.severity,
        proposed_code=request.proposed_code,
        workspace_root=request.workspace_root,
        workspace_id=request.workspace_id,
        approval=request.approval,
        original_code_hash=request.original_code_hash,
        expected_original_code=request.expected_original_code,
    )

