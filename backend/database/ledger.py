import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ledger.db"
WORKSPACE_ROOT = os.getenv("ARCHITEX_WORKSPACE")


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


class LedgerEntry(BaseModel):
    id: int
    timestamp: str
    file_path: str
    previous_code: str
    new_code: str
    severity: Severity
    changed_by: ChangedBy
    status: LedgerStatus


class LedgerLogRequest(BaseModel):
    file_path: str = Field(..., min_length=1)
    previous_code: str = ""
    new_code: str = ""
    severity: Severity
    changed_by: ChangedBy = ChangedBy.AI
    workspace_root: str | None = None


class RollbackRequest(BaseModel):
    id: int
    workspace_root: str | None = None


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                file_path TEXT NOT NULL,
                previous_code TEXT NOT NULL,
                new_code TEXT NOT NULL,
                severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
                changed_by TEXT NOT NULL CHECK (changed_by IN ('AI', 'User')),
                status TEXT NOT NULL CHECK (status IN ('active', 'rolled_back'))
            )
            """
        )


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_log(
    file_path: str,
    previous_code: str,
    new_code: str,
    severity: str | Severity,
    changed_by: str | ChangedBy = ChangedBy.AI,
    workspace_root: str | None = None,
) -> LedgerEntry:
    severity_value = Severity(str(severity).lower()).value
    changed_value = ChangedBy.AI if str(changed_by).lower() == "ai" else ChangedBy.USER.value
    path = Path(file_path).expanduser()
    if path.is_absolute() or workspace_root or WORKSPACE_ROOT:
        stored_path = str(_resolve_path(file_path, workspace_root))
    else:
        stored_path = file_path
    timestamp = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ledger (
                timestamp, file_path, previous_code, new_code, severity, changed_by, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                stored_path,
                previous_code,
                new_code,
                severity_value,
                changed_value,
                LedgerStatus.ACTIVE.value,
            ),
        )
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (cursor.lastrowid,)).fetchone()

    return _row_to_entry(row)


def rollback_change(entry_id: int, workspace_root: str | None = None) -> LedgerEntry:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise KeyError(f"Ledger entry {entry_id} not found.")
        if row["status"] == LedgerStatus.ROLLED_BACK.value:
            raise ValueError(f"Ledger entry {entry_id} is already rolled back.")

        stored = Path(row["file_path"]).expanduser()
        if stored.is_absolute() or workspace_root or WORKSPACE_ROOT:
            target = _resolve_path(row["file_path"], workspace_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(row["previous_code"], encoding="utf-8")

        conn.execute(
            "UPDATE ledger SET status = ? WHERE id = ?",
            (LedgerStatus.ROLLED_BACK.value, entry_id),
        )
        updated = conn.execute("SELECT * FROM ledger WHERE id = ?", (entry_id,)).fetchone()

    return _row_to_entry(updated)


def list_logs() -> list[LedgerEntry]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM ledger ORDER BY id DESC").fetchall()
    return [_row_to_entry(row) for row in rows]


def get_entry(entry_id: int) -> LedgerEntry | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM ledger WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_entry(row) if row else None


def _resolve_path(file_path: str, workspace_root: str | None = None) -> Path:
    root_value = workspace_root or WORKSPACE_ROOT
    path = Path(file_path).expanduser()

    if path.is_absolute():
        resolved = path.resolve()
        if root_value:
            root = Path(root_value).expanduser().resolve()
            if not _is_relative_to(resolved, root):
                raise ValueError("file_path is outside the workspace.")
        return resolved

    if not root_value:
        raise ValueError("Relative file_path requires workspace_root or ARCHITEX_WORKSPACE.")

    root = Path(root_value).expanduser().resolve()
    resolved = (root / path).resolve()
    if not _is_relative_to(resolved, root):
        raise ValueError("file_path is outside the workspace.")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _row_to_entry(row: sqlite3.Row | dict[str, Any]) -> LedgerEntry:
    data = dict(row)
    return LedgerEntry.model_validate(data)


init_db()
