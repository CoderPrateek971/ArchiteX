import hashlib
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
                after_hash TEXT DEFAULT NULL
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
    db_path: Optional[Path] = None,
) -> LedgerEntry:
    """Record a code modification in the audit ledger, optionally writing safely to disk."""
    sev_str = str(severity.value if isinstance(severity, Severity) else severity).lower()
    chg_str = "AI" if str(changed_by.value if isinstance(changed_by, ChangedBy) else changed_by).lower() == "ai" else "User"
    stat_str = str(status.value if isinstance(status, LedgerStatus) else status).lower()

    # Enforce workspace path containment
    resolved_target = _resolve_path(file_path, workspace_root)
    stored_path = str(resolved_target)

    actual_previous = previous_code
    if resolved_target.is_file() and (not previous_code or previous_code == "Original code recorded in ledger"):
        try:
            actual_previous = resolved_target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            actual_previous = previous_code

    if write_to_disk and new_code:
        _atomic_write(resolved_target, new_code)

    before_hash = _compute_hash(actual_previous) if actual_previous else None
    after_hash = _compute_hash(new_code) if new_code else None
    timestamp = datetime.now(timezone.utc).isoformat()

    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO ledger (
                timestamp, file_path, previous_code, new_code, severity, changed_by,
                details, issue_id, validation_result, status, rollback_ref, before_hash, after_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (cursor.lastrowid,)).fetchone()

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

        # 1. Enforce workspace path containment
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
    return LedgerEntry.model_validate(data)


# Auto-migrate/initialize on import
init_db()
