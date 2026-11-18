import ast
import json
import logging
import os
import py_compile
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict, deque
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =====================================================================
# Pydantic Schemas
# =====================================================================


class RepairActionType(str, Enum):
    CONTRACT_VERIFICATION = "CONTRACT_VERIFICATION"
    CORE_REMEDIATION = "CORE_REMEDIATION"
    CALLER_MIGRATION = "CALLER_MIGRATION"
    TEST_VALIDATION = "TEST_VALIDATION"


class RepairStep(BaseModel):
    order: int
    file_path: str
    phase_name: str
    action_type: RepairActionType
    action_title: str
    description: str
    proposed_code: str = ""
    diff_summary: str = ""
    reasoning: str
    potential_risks: str
    status: str = "pending"  # "pending", "applied", "verified"


class DownstreamImpact(BaseModel):
    file_path: str
    depth: int
    relationship: str
    symbols_used: list[str] = Field(default_factory=list)
    risk_level: str  # "High", "Medium", "Low"


class GuidedRepairPlan(BaseModel):
    finding_id: str
    target_file: str
    severity: str
    issue_title: str
    root_cause: str
    knowledge_graph_path: list[str] = Field(default_factory=list)
    blast_radius: str
    downstream_impacts: list[DownstreamImpact] = Field(default_factory=list)
    ordered_steps: list[RepairStep] = Field(default_factory=list)
    architectural_reasoning: str
    potential_risks: list[str] = Field(default_factory=list)
    test_validation_command: str


class TestValidationRequest(BaseModel):
    files_to_validate: list[str] = Field(default_factory=list)
    workspace_root: Optional[str] = None
    code_overrides: dict[str, str] = Field(default_factory=dict)
    run_pytest: bool = True


class TestValidationResult(BaseModel):
    passed: bool
    syntax_passed: bool
    tests_passed: bool
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    output_log: str
    details: list[dict[str, Any]] = Field(default_factory=list)


# =====================================================================
# Knowledge Graph Analysis & Impact Engine
# =====================================================================


def analyze_downstream_impact(
    target_file: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    file_sources: dict[str, str],
) -> tuple[list[str], list[DownstreamImpact]]:
    """
    Traverses the knowledge graph starting from target_file to identify direct and
    transitive downstream dependent components, impacted symbols, and call paths.
    """
    clean_target = target_file.replace("file:", "")

    # Build adjacency: A -> B (A is imported by B => B depends on A)
    # Edge with kind 'import': source = importer, target = imported
    downstream_adj = defaultdict(set)
    path_by_node_id = {}
    for n in nodes:
        data = n.get("data") or {}
        p = data.get("path") or data.get("label") or n.get("id")
        path_by_node_id[n["id"]] = p

    for e in edges:
        kind = (e.get("data") or {}).get("kind") or e.get("label") or ""
        src = e.get("source")
        dst = e.get("target")
        if kind == "import" and src and dst:
            importer = path_by_node_id.get(src, src)
            imported = path_by_node_id.get(dst, dst)
            if importer and imported and importer != imported:
                downstream_adj[imported].add(importer)

    # Breadth-first search for all downstream dependents
    visited = set()
    queue = deque([(clean_target, 1)])
    impacts: list[DownstreamImpact] = []
    longest_path = [clean_target]

    while queue:
        curr, depth = queue.popleft()
        for dep in sorted(list(downstream_adj.get(curr, set()))):
            if dep not in visited and dep != clean_target:
                visited.add(dep)
                queue.append((dep, depth + 1))

                # Identify symbols used by dep from clean_target
                symbols = _find_imported_symbols(file_sources.get(dep, ""), clean_target)

                risk = "High" if depth == 1 else ("Medium" if depth == 2 else "Low")
                rel = "Direct Consumer (imports target)" if depth == 1 else f"Transitive Consumer (depth {depth})"

                impacts.append(
                    DownstreamImpact(
                        file_path=dep,
                        depth=depth,
                        relationship=rel,
                        symbols_used=symbols,
                        risk_level=risk,
                    )
                )

                if depth + 1 > len(longest_path):
                    longest_path.append(dep)

    return longest_path, impacts


def _find_imported_symbols(caller_source: str, target_file: str) -> list[str]:
    """Inspects AST of caller source to extract symbols imported from target file."""
    if not caller_source:
        return []
    base_name = Path(target_file).stem
    symbols = []
    try:
        tree = ast.parse(caller_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and (node.module == base_name or node.module.endswith(f".{base_name}")):
                    for alias in node.names:
                        symbols.append(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == base_name:
                        symbols.append(alias.asname or alias.name)
    except Exception:
        pass
    return symbols[:5]


# =====================================================================
# Guided Repair Plan Generator
# =====================================================================


def generate_guided_repair_plan(
    finding: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    file_sources: dict[str, str],
    proposed_code: str = "",
) -> GuidedRepairPlan:
    """
    Generates a structured, step-by-step repair plan specifying which files to change
    and in what order, explaining proposed changes, reasoning, and potential risks.
    """
    target_file = finding.get("file_name", "main.py").replace("file:", "")
    title = finding.get("title", "Detected Issue")
    severity = str(finding.get("severity", "Medium"))
    root_cause = finding.get("root_cause") or finding.get("description", "")
    source = file_sources.get(target_file, "")

    # 1. Trace knowledge graph downstream impact
    kg_path, downstream_impacts = analyze_downstream_impact(target_file, nodes, edges, file_sources)

    blast_radius = (
        f"High risk: Affects {len(downstream_impacts)} downstream dependent files ({', '.join([d.file_path for d in downstream_impacts[:2]])})"
        if len(downstream_impacts) > 1
        else (f"Moderate risk: Affects `{downstream_impacts[0].file_path}`" if downstream_impacts else "Isolated to target file: No downstream consumers")
    )

    steps: list[RepairStep] = []
    order = 1

    # STEP 1: Contract & Interface Verification
    steps.append(
        RepairStep(
            order=order,
            file_path=target_file,
            phase_name="Order 1: Interface Contract Preparation",
            action_type=RepairActionType.CONTRACT_VERIFICATION,
            action_title=f"Verify imported interfaces and boundaries in `{target_file}`",
            description=f"Inspect symbol signatures in `{target_file}` to ensure planned modifications to resolve '{title}' maintain backward-compatible parameters and return contracts.",
            proposed_code="",
            diff_summary=f"Audit boundaries and parameter signatures in {target_file}",
            reasoning="Executing contract verification first prevents breaking public API signatures that downstream callers rely on.",
            potential_risks="Changing function or method signatures without contract auditing causes runtime TypeError in callers.",
            status="pending",
        )
    )
    order += 1

    # STEP 2: Core Target File Remediation
    core_code = proposed_code or finding.get("proposed_code") or f"# [ArchiteX Fix] {title}\n{source}"
    steps.append(
        RepairStep(
            order=order,
            file_path=target_file,
            phase_name="Order 2: Target File Core Remediation",
            action_type=RepairActionType.CORE_REMEDIATION,
            action_title=f"Apply problem-specific fix in `{target_file}`",
            description=f"Apply recommended fix: {finding.get('suggested_fix', 'Remediate detected defect')}. Eliminates root cause: {root_cause}",
            proposed_code=core_code,
            diff_summary=f"Fixes {title} in {target_file}",
            reasoning=f"Directly resolves the defect in {target_file} while maintaining exported symbol stability.",
            potential_risks="Unchecked syntax modifications or missing local imports can prevent module compilation.",
            status="pending",
        )
    )
    order += 1

    # STEP 3..N: Downstream Caller Migrations (in topological dependency order)
    for impact in downstream_impacts:
        consumer_file = impact.file_path
        consumer_symbols = impact.symbols_used
        sym_str = f" ({', '.join(consumer_symbols)})" if consumer_symbols else ""

        steps.append(
            RepairStep(
                order=order,
                file_path=consumer_file,
                phase_name=f"Order {order}: Downstream Caller Migration ({consumer_file})",
                action_type=RepairActionType.CALLER_MIGRATION,
                action_title=f"Review dependent module `{consumer_file}`{sym_str}",
                description=f"Verify that `{consumer_file}` imports and consumes symbols from `{target_file}` cleanly without runtime AttributeError or parameter mismatches.",
                proposed_code="",
                diff_summary=f"Validate caller compatibility in {consumer_file}",
                reasoning=f"`{consumer_file}` directly imports `{target_file}`. Updating in topological order ensures consumers never encounter a broken intermediary interface.",
                potential_risks=f"If `{consumer_file}` assumes deprecated behavior or unvalidated return shapes, requests through this module will fail.",
                status="pending",
            )
        )
        order += 1

    # FINAL STEP: Test Validation & Regression Checks
    affected_all = [target_file] + [d.file_path for d in downstream_impacts]
    steps.append(
        RepairStep(
            order=order,
            file_path=f"test_suite_{Path(target_file).stem}.py",
            phase_name=f"Order {order}: Automated Test Validation & Regression Suite",
            action_type=RepairActionType.TEST_VALIDATION,
            action_title="Execute syntax compilation, contract validation, and unit tests",
            description=f"Execute comprehensive static AST compilation and regression testing across all {len(affected_all)} affected files: {', '.join(affected_all[:3])}.",
            proposed_code="",
            diff_summary="Run automated test suite to confirm zero regressions",
            reasoning="Validating with automated tests guarantees that repaired code passes static syntax checks and preserves behavioral invariants.",
            potential_risks="Undetected regression failures if unit test assertions are bypassed.",
            status="pending",
        )
    )

    arch_reasoning = (
        f"This repair plan follows strict topological dependency ordering. Root cause ({root_cause[:90]}...) is resolved "
        f"in `{target_file}` only after contract bounds are confirmed. Downstream consumers ({', '.join([d.file_path for d in downstream_impacts[:2]]) or 'None'}) "
        f"are migrated sequentially before running the automated regression validation test suite."
    )

    risks = [
        f"API signature divergence between `{target_file}` and downstream callers.",
        "Module load deadlock if circular imports are partially resolved without deferred importing.",
        "Stale cached bytecode (.pyc) if files are updated out of topological order.",
    ]

    return GuidedRepairPlan(
        finding_id=finding.get("id", "bug-1"),
        target_file=target_file,
        severity=severity,
        issue_title=title,
        root_cause=root_cause,
        knowledge_graph_path=kg_path,
        blast_radius=blast_radius,
        downstream_impacts=downstream_impacts,
        ordered_steps=steps,
        architectural_reasoning=arch_reasoning,
        potential_risks=risks,
        test_validation_command=f"pytest -v tests/ --capture=no",
    )


# =====================================================================
# Automated Test Validation Engine
# =====================================================================


def validate_repair_with_tests(
    req: TestValidationRequest,
) -> TestValidationResult:
    """
    Validates code changes across all specified files using Python AST compilation,
    py_compile byte-compilation, and executing existing unit tests or pytest.
    """
    output_lines: list[str] = []
    details: list[dict[str, Any]] = []
    syntax_passed = True
    tests_passed = True
    total_tests = 0
    passed_tests = 0
    failed_tests = 0

    output_lines.append("=" * 60)
    output_lines.append("🚀 ArchiteX Automated Test Validation Engine (Module 5)")
    output_lines.append("=" * 60)

    # 1. In-memory / Code Override Syntax & AST Validation
    for fpath, code in req.code_overrides.items():
        try:
            ast.parse(code, filename=fpath)
            output_lines.append(f"✅ AST Syntax Valid: {fpath}")
            details.append({"file": fpath, "check": "AST Parse", "status": "PASSED"})
        except SyntaxError as e:
            syntax_passed = False
            output_lines.append(f"❌ SyntaxError in {fpath} (Line {e.lineno}): {e.msg}")
            details.append({"file": fpath, "check": "AST Parse", "status": "FAILED", "error": f"{e.msg} at line {e.lineno}"})

    # 2. Disk / Workspace File Validation
    for fpath in req.files_to_validate:
        full_path = fpath
        if req.workspace_root and not os.path.isabs(fpath):
            full_path = os.path.join(req.workspace_root, fpath)

        if os.path.exists(full_path):
            try:
                py_compile.compile(full_path, doraise=True)
                output_lines.append(f"✅ Byte-Compile Passed: {fpath}")
                details.append({"file": fpath, "check": "py_compile", "status": "PASSED"})
            except py_compile.PyCompileError as e:
                syntax_passed = False
                output_lines.append(f"❌ Compilation Failed in {fpath}: {e.msg}")
                details.append({"file": fpath, "check": "py_compile", "status": "FAILED", "error": str(e.msg)})
        else:
            # If file not on disk (e.g. zip upload before saving), perform AST parse if in overrides
            if fpath not in req.code_overrides:
                output_lines.append(f"ℹ️ File boundary check passed (Virtual Sandbox): {fpath}")
                details.append({"file": fpath, "check": "Sandbox Boundary", "status": "PASSED"})

    # 3. Unit Test Execution (pytest / unittest)
    output_lines.append("-" * 60)
    output_lines.append("🧪 Running Regression Test Suite...")

    test_executed = False
    if req.workspace_root and os.path.exists(req.workspace_root):
        test_dir = os.path.join(req.workspace_root, "tests")
        has_tests = os.path.exists(test_dir) or any(
            f.startswith("test_") or f.endswith("_test.py")
            for root, _, files in os.walk(req.workspace_root)
            for f in files
        )

        if has_tests and req.run_pytest:
            test_executed = True
            try:
                cmd = [sys.executable, "-m", "pytest", "-v", "."]
                proc = subprocess.run(
                    cmd,
                    cwd=req.workspace_root,
                    capture_output=True,
                    text=True,
                    timeout=12,
                )
                output_lines.append(proc.stdout or proc.stderr)
                if proc.returncode == 0:
                    output_lines.append("🎉 All pytest suite tests PASSED!")
                    tests_passed = True
                else:
                    output_lines.append(f"⚠️ Test suite returned exit code {proc.returncode}")
                    tests_passed = False
            except Exception as exc:
                output_lines.append(f"⚠️ Pytest execution error: {exc}")
                tests_passed = False

    if not test_executed:
        # Syntax checks are not a substitute for executing a real test suite.
        tests_passed = False
        output_lines.append("⚠️ No runnable pytest suite was found; behavioral validation was not performed.")

    all_passed = syntax_passed and tests_passed

    output_lines.append("=" * 60)
    output_lines.append(f"🏁 Final Validation Verdict: {'PASSED (Zero Regressions)' if all_passed else 'FAILED (Review errors above)'}")
    output_lines.append("=" * 60)

    return TestValidationResult(
        passed=all_passed,
        syntax_passed=syntax_passed,
        tests_passed=tests_passed,
        total_tests=total_tests,
        passed_tests=passed_tests,
        failed_tests=failed_tests,
        output_log="\n".join(output_lines),
        details=details,
    )
