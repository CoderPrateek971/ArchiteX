import hashlib
import json
import os
import sqlite3
import ast
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ChangedBy(str, Enum):
    AI = "AI"
    USER = "User"


class LedgerStatus(str, Enum):
    ACTIVE = "active"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ConflictError(Exception):
    """Raised when file content conflicts with recorded after-change state during rollback."""
    pass


class LedgerEntry(BaseModel):
    id: int
    timestamp: str
    file_path: str
    previous_code: str = ""
    new_code: str = ""
    severity: str
    changed_by: str
    details: Optional[str] = None
    issue_id: Optional[str] = None
    validation_result: Optional[str] = None
    status: str
    rollback_ref: Optional[int] = None
    before_hash: Optional[str] = None
    after_hash: Optional[str] = None
    file_changes: Optional[list[dict[str, str]]] = None


class LedgerLogRequest(BaseModel):
    file_path: str = Field(..., min_length=1)
    previous_code: str = ""
    new_code: str = ""
    severity: str
    changed_by: str = "AI"
    details: Optional[str] = None
    issue_id: Optional[str] = None
    validation_result: Optional[str] = None
    workspace_root: Optional[str] = None


class RollbackRequest(BaseModel):
    id: int
    workspace_root: Optional[str] = None


def get_db_path() -> Path:
    env_path = os.getenv("ARCHITEX_LEDGER_DB")
    if env_path:
        return Path(env_path).resolve()
    backend_db = Path(__file__).resolve().parent.parent / "ledger.db"
    return backend_db


def _normalize_code(code: str) -> str:
    """Normalize line endings and whitespace for cross-platform comparison."""
    if not code:
        return ""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def _compute_hash(code: str) -> str:
    return hashlib.sha256(_normalize_code(code).encode("utf-8")).hexdigest()


@contextmanager
def _connect(db_path: Path | None = None):
    target = db_path or get_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Initialize SQLite database with safe migrations preserving existing data."""
    target_db = db_path or get_db_path()
    target_db.parent.mkdir(parents=True, exist_ok=True)
    with _connect(target_db) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                file_path TEXT NOT NULL,
                previous_code TEXT NOT NULL DEFAULT '',
                new_code TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'low',
                changed_by TEXT NOT NULL DEFAULT 'AI',
                details TEXT DEFAULT '',
                issue_id TEXT DEFAULT NULL,
                validation_result TEXT DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                rollback_ref INTEGER DEFAULT NULL,
                before_hash TEXT DEFAULT NULL,
                after_hash TEXT DEFAULT NULL,
                file_changes TEXT DEFAULT NULL
            )
            """
        )
        # Safe migration for existing schemas without data loss
        existing_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(ledger)").fetchall()
        }
        columns_to_add = {
            "details": "TEXT DEFAULT ''",
            "issue_id": "TEXT DEFAULT NULL",
            "validation_result": "TEXT DEFAULT NULL",
            "rollback_ref": "INTEGER DEFAULT NULL",
            "before_hash": "TEXT DEFAULT NULL",
            "after_hash": "TEXT DEFAULT NULL",
            "file_changes": "TEXT DEFAULT NULL",
        }
        for col_name, col_def in columns_to_add.items():
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE ledger ADD COLUMN {col_name} {col_def}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_path(file_path: str, workspace_root: str | None = None) -> Path:
    """Resolve file path within workspace and block path traversal outside boundaries."""
    clean_path = file_path.replace("file:", "").strip()
    root_value = workspace_root or os.getenv("ARCHITEX_WORKSPACE")

    path = Path(clean_path).expanduser()
    if path.is_absolute():
        resolved = path.resolve()
        if root_value:
            root = Path(root_value).expanduser().resolve()
            if not _is_relative_to(resolved, root):
                raise ValueError(f"Path traversal blocked: '{file_path}' is outside workspace '{root}'.")
        return resolved

    if not root_value:
        root = Path.cwd().resolve()
    else:
        root = Path(root_value).expanduser().resolve()

    resolved = (root / path).resolve()
    if not _is_relative_to(resolved, root):
        raise ValueError(f"Path traversal blocked: '{file_path}' is outside workspace '{root}'.")
    return resolved


def _atomic_write(target_path: Path, content: str) -> None:
    """Safely and atomically write content to target path."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.parent / f".tmp_{target_path.name}_{uuid.uuid4().hex}"
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(target_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def insert_log(
    file_path: str,
    previous_code: str,
    new_code: str,
    severity: str | Severity,
    changed_by: str | ChangedBy = ChangedBy.AI,
    details: Optional[str] = None,
    issue_id: Optional[str] = None,
    validation_result: Optional[str] = None,
    status: str | LedgerStatus = LedgerStatus.ACTIVE,
    rollback_ref: Optional[int] = None,
    workspace_root: Optional[str] = None,
    write_to_disk: bool = False,
    record_only: bool = False,
    file_changes: Optional[list[dict[str, str]]] = None,
    db_path: Optional[Path] = None,
) -> LedgerEntry:
    """Record a code modification in the audit ledger, optionally writing safely to disk."""
    sev_str = str(severity.value if isinstance(severity, Severity) else severity).lower()
    chg_str = "AI" if str(changed_by.value if isinstance(changed_by, ChangedBy) else changed_by).lower() == "ai" else "User"
    stat_str = str(status.value if isinstance(status, LedgerStatus) else status).lower()

    snapshots: list[dict[str, str]] = []
    if file_changes:
        if record_only:
            raise ValueError("A combined file change cannot be recorded as read-only.")
        seen_paths: set[str] = set()
        for change in file_changes:
            change_path = str(change.get("file_path") or "").strip()
            if not change_path or change_path in seen_paths:
                raise ValueError("Combined changes must contain unique file paths.")
            seen_paths.add(change_path)
            target = _resolve_path(change_path, workspace_root)
            if not target.is_file():
                raise FileNotFoundError(f"Target file for combined change does not exist: {target}")
            before = target.read_text(encoding="utf-8", errors="replace")
            expected = change.get("expected_code")
            if expected is not None and _normalize_code(before) != _normalize_code(expected):
                raise ConflictError(
                    f"Cannot save combined repair: '{target.name}' changed since it was scanned. "
                    "Refresh the repository and review the repair again."
                )
            after = str(change.get("new_code") or "")
            snapshots.append({
                "file_path": str(target),
                "previous_code": before,
                "new_code": after,
                "before_hash": _compute_hash(before),
                "after_hash": _compute_hash(after),
            })

        resolved_target = Path(snapshots[0]["file_path"])
        stored_path = str(resolved_target)
        actual_previous = snapshots[0]["previous_code"]
        new_code = snapshots[0]["new_code"]
    else:
        # Enforce workspace path containment
        resolved_target = _resolve_path(file_path, workspace_root)
        stored_path = str(resolved_target)

        actual_previous = previous_code
        if resolved_target.is_file() and (not previous_code or previous_code == "Original code recorded in ledger"):
            try:
                actual_previous = resolved_target.read_text(encoding="utf-8", errors="replace")
            except Exception:
                actual_previous = previous_code

    # Confirmation and user feedback events describe an existing file state; they
    # must not replace the file with notes or a duplicate copy of a prior patch.
    if record_only:
        if not resolved_target.is_file():
            raise FileNotFoundError(f"Target file for ledger event does not exist: {resolved_target}")
        new_code = actual_previous

    written_snapshots: list[dict[str, str]] = []
    try:
        if snapshots and write_to_disk:
            for snapshot in snapshots:
                _atomic_write(Path(snapshot["file_path"]), snapshot["new_code"])
                written_snapshots.append(snapshot)
        elif write_to_disk and new_code:
            _atomic_write(resolved_target, new_code)
    except Exception:
        for snapshot in reversed(written_snapshots):
            _atomic_write(Path(snapshot["file_path"]), snapshot["previous_code"])
        raise

    before_hash = _compute_hash(actual_previous) if actual_previous else None
    after_hash = _compute_hash(new_code) if new_code else None
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        with _connect(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO ledger (
                    timestamp, file_path, previous_code, new_code, severity, changed_by,
                    details, issue_id, validation_result, status, rollback_ref, before_hash, after_hash, file_changes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    stored_path,
                    actual_previous,
                    new_code,
                    sev_str,
                    chg_str,
                    details or "",
                    issue_id,
                    validation_result,
                    stat_str,
                    rollback_ref,
                    before_hash,
                    after_hash,
                    json.dumps(snapshots) if snapshots else None,
                ),
            )
            row = conn.execute("SELECT * FROM ledger WHERE id = ?", (cursor.lastrowid,)).fetchone()
    except Exception:
        for snapshot in reversed(written_snapshots):
            _atomic_write(Path(snapshot["file_path"]), snapshot["previous_code"])
        raise

    return _row_to_entry(row)


def rollback_change(
    entry_id: int,
    workspace_root: str | None = None,
    db_path: Optional[Path] = None,
) -> LedgerEntry:
    """
    Selectively roll back a change by entry ID with conflict detection and post-rollback validation.
    Never silently overwrites newer developer edits.
    """
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise KeyError(f"Ledger entry {entry_id} not found.")

        if row["status"] == LedgerStatus.ROLLED_BACK.value:
            raise ValueError(f"Ledger entry {entry_id} is already rolled back.")

        if row["file_changes"]:
            return _rollback_file_set(conn, row, entry_id, workspace_root)

        # 1. Resolve the workspace recorded with this change. A currently
        # selected upload may be a different workspace than this historical entry.
        recorded_path = Path(row["file_path"].replace("file:", "").strip()).expanduser()
        if recorded_path.is_absolute() and not workspace_root:
            target_file = recorded_path.resolve()
            managed_workspaces = Path(__file__).resolve().parent.parent / "data" / "workspaces"
            allowed_roots = [managed_workspaces]
            configured_root = os.getenv("ARCHITEX_WORKSPACE")
            if configured_root:
                allowed_roots.append(Path(configured_root).expanduser().resolve())
            if not any(_is_relative_to(target_file, root) for root in allowed_roots):
                raise ValueError(
                    f"Rollback target '{target_file}' is outside the managed workspace folders."
                )
        else:
            target_file = _resolve_path(row["file_path"], workspace_root)
        if not target_file.is_file():
            raise FileNotFoundError(f"Target file for rollback does not exist: {target_file}")

        # 2. Conflict Detection: compare current file contents with recorded new version
        current_content = target_file.read_text(encoding="utf-8", errors="replace")
        current_norm = _normalize_code(current_content)
        recorded_new_norm = _normalize_code(row["new_code"] or "")

        if current_norm != recorded_new_norm:
            # File was modified after this change was applied
            raise ConflictError(
                f"Rollback conflict on '{target_file.name}': file has been modified since change #{entry_id} "
                f"was recorded. Current content does not match the recorded post-change version. "
                f"Rollback rejected to prevent overwriting newer changes."
            )

        # 3. Safe restoration with rollback validation
        pre_rollback_state = current_content
        restored_code = row["previous_code"] or ""

        _atomic_write(target_file, restored_code)

        # 4. Validate restored file
        if target_file.suffix == ".py":
            try:
                ast.parse(restored_code, filename=str(target_file))
            except SyntaxError as syn_err:
                # Restoration causes syntax error: restore pre-rollback state immediately
                _atomic_write(target_file, pre_rollback_state)
                raise ValueError(
                    f"Rollback validation failed: restored code contains SyntaxError at line {syn_err.lineno}: {syn_err.msg}. "
                    f"Target file restored to pre-rollback state."
                )
            except Exception as exc:
                _atomic_write(target_file, pre_rollback_state)
                raise ValueError(
                    f"Rollback validation failed: {exc}. Target file restored to pre-rollback state."
                )

        # 5. Update status of the rolled back entry
        conn.execute(
            "UPDATE ledger SET status = ? WHERE id = ?",
            (LedgerStatus.ROLLED_BACK.value, entry_id),
        )

        # 6. Record rollback activity in audit history
        rollback_timestamp = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO ledger (
                timestamp, file_path, previous_code, new_code, severity, changed_by,
                details, issue_id, validation_result, status, rollback_ref, before_hash, after_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rollback_timestamp,
                str(target_file),
                current_content,
                restored_code,
                row["severity"],
                ChangedBy.USER.value,
                f"Rollback of change #{entry_id}",
                row["issue_id"],
                "PASSED",
                LedgerStatus.ACTIVE.value,
                entry_id,
                _compute_hash(current_content),
                _compute_hash(restored_code),
            ),
        )

        updated = conn.execute("SELECT * FROM ledger WHERE id = ?", (entry_id,)).fetchone()

    return _row_to_entry(updated)


def _rollback_file_set(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    entry_id: int,
    workspace_root: str | None,
) -> LedgerEntry:
    """Atomically restore every file captured by one combined repair entry."""
    snapshots = json.loads(row["file_changes"])
    managed_workspaces = Path(__file__).resolve().parent.parent / "data" / "workspaces"
    configured_root = os.getenv("ARCHITEX_WORKSPACE")
    allowed_roots = [managed_workspaces]
    if configured_root:
        allowed_roots.append(Path(configured_root).expanduser().resolve())

    current_states: list[tuple[Path, str, str]] = []
    for snapshot in snapshots:
        recorded_path = snapshot["file_path"]
        if workspace_root:
            target = _resolve_path(recorded_path, workspace_root)
        else:
            target = Path(recorded_path).expanduser().resolve()
            if not target.is_absolute() or not any(_is_relative_to(target, root) for root in allowed_roots):
                raise ValueError(f"Rollback target '{target}' is outside the managed workspace folders.")
        if not target.is_file():
            raise FileNotFoundError(f"Target file for rollback does not exist: {target}")

        current = target.read_text(encoding="utf-8", errors="replace")
        if _normalize_code(current) != _normalize_code(snapshot.get("new_code") or ""):
            raise ConflictError(
                f"Rollback conflict on '{target.name}': file has been modified since combined change #{entry_id}. "
                "No files were restored."
            )
        previous = snapshot.get("previous_code") or ""
        if target.suffix == ".py":
            try:
                ast.parse(previous, filename=str(target))
            except SyntaxError as exc:
                raise ValueError(
                    f"Rollback validation failed: restored code for '{target.name}' has a syntax error at line {exc.lineno}."
                ) from exc
        current_states.append((target, current, previous))

    written: list[tuple[Path, str]] = []
    try:
        for target, current, previous in current_states:
            _atomic_write(target, previous)
            written.append((target, current))
    except Exception:
        for target, current in reversed(written):
            _atomic_write(target, current)
        raise

    first_target, first_current, first_previous = current_states[0]
    rollback_snapshots = [
        {
            "file_path": str(target),
            "previous_code": current,
            "new_code": previous,
            "before_hash": _compute_hash(current),
            "after_hash": _compute_hash(previous),
        }
        for target, current, previous in current_states
    ]
    try:
        conn.execute(
            "UPDATE ledger SET status = ? WHERE id = ?",
            (LedgerStatus.ROLLED_BACK.value, entry_id),
        )
        conn.execute(
            """
            INSERT INTO ledger (
                timestamp, file_path, previous_code, new_code, severity, changed_by,
                details, issue_id, validation_result, status, rollback_ref, before_hash, after_hash, file_changes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                str(first_target),
                first_current,
                first_previous,
                row["severity"],
                ChangedBy.USER.value,
                f"Rollback of combined change #{entry_id} ({len(rollback_snapshots)} files)",
                row["issue_id"],
                "PASSED",
                LedgerStatus.ACTIVE.value,
                entry_id,
                _compute_hash(first_current),
                _compute_hash(first_previous),
                json.dumps(rollback_snapshots),
            ),
        )
        updated = conn.execute("SELECT * FROM ledger WHERE id = ?", (entry_id,)).fetchone()
    except Exception:
        for target, current, _previous in current_states:
            _atomic_write(target, current)
        raise
    return _row_to_entry(updated)


def list_logs(db_path: Optional[Path] = None) -> list[LedgerEntry]:
    """Retrieve all change logs ordered from newest to oldest."""
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM ledger ORDER BY id DESC").fetchall()
    return [_row_to_entry(row) for row in rows]


def get_entry(entry_id: int, db_path: Optional[Path] = None) -> LedgerEntry | None:
    """Retrieve a single change log by ID."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_entry(row) if row else None


def _row_to_entry(row: sqlite3.Row | dict[str, Any]) -> LedgerEntry:
    data = dict(row)
    if data.get("file_changes"):
        data["file_changes"] = json.loads(data["file_changes"])
    else:
        data["file_changes"] = None
    return LedgerEntry.model_validate(data)


# Auto-migrate/initialize on import
init_db()
