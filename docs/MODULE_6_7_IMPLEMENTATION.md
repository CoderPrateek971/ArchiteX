# ArchiteX Modules 6 & 7 Implementation Guide

This document details the architectural design, workflow, data schemas, API contracts, verification guarantees, and test suites for:
- **Module 6: Automatic Repair Engine** (`backend/services/repair_engine.py`)
- **Module 7: Change History and Rollback** (`backend/database/ledger.py`)

---

## 1. Architecture Overview

ArchiteX provides an end-to-end AI-assisted software engineering platform. While other modules focus on architectural comprehension (Module 1), AST dependency modeling (Module 2), repository scanning (Module 3), multi-model routing (Module 4), and guided repair planning (Module 5), **Modules 6 and 7 provide the execution, safety, auditing, and reversal foundations of the platform**.

```
                           +----------------------------+
                           |  Frontend (UI / Ledger)    |
                           +--------------+-------------+
                                          |
                +-------------------------+-------------------------+
                |                                                   |
                v                                                   v
      [POST /api/repair/apply]                          [POST /api/ledger/rollback]
                |                                                   |
                v                                                   v
+-------------------------------+                   +-------------------------------+
| Module 6: Repair Engine       |                   | Module 7: Ledger & Rollback   |
| (services/repair_engine.py)   |                   | (database/ledger.py)          |
|-------------------------------|                   |-------------------------------|
| 1. Approval Gate              |                   | 1. Workspace Boundary Check   |
| 2. Severity Policy (LOW only) |                   | 2. File State Comparison      |
| 3. Workspace Path Containment |                   | 3. Conflict Detection (409)   |
| 4. Concurrency Guard          |                   | 4. Reversible Atomic Write    |
| 5. Reversible Atomic Write    |                   | 5. Restored Syntax Validation |
| 6. AST & Pytest Validation    |                   | 6. Rollback Audit Logging     |
+---------------+---------------+                   +---------------+---------------+
                |                                                   |
                +-------------------------+-------------------------+
                                          |
                                          v
                           +----------------------------+
                           | SQLite Audit Ledger        |
                           | (backend/ledger.db)        |
                           +----------------------------+
```

---

## 2. Module 6 — Automatic Repair Engine

### 2.1 Core Purpose & Safety Policy
Automated code modifications can introduce regressions if applied indiscriminately. Module 6 enforces strict constraints:
1. **Explicit Approval Gate:** Any repair requires `approval=True`. Unapproved requests are rejected immediately.
2. **Severity Restriction:** **Only LOW severity issues** (such as dead imports, missing return type hints, weak naming conventions, or simple formatting debt) are eligible for automatic application. Medium and High severity issues are rejected with an explicit explanation instructing the developer to use guided review.
3. **Workspace Path Containment:** Enforces strict containment to block directory traversal attacks (e.g., `../../etc/passwd` or symbolic escape vectors).
4. **Concurrency Guard:** Reads the target file before modification and compares its SHA-256 hash or content with `original_code_hash` / `expected_original_code`. If a concurrent change occurred, the repair is aborted to prevent race conditions.
5. **Sandboxed AST & Test Validation:** Proposed code is parsed statically with Python AST (`ast.parse`). If valid, it is atomically swapped onto disk and evaluated against the existing regression test suite (`pytest`) with a strict execution timeout.
6. **Automatic Rollback on Failure:** If Python AST compilation fails or unit tests fail, the original source code is instantly and atomically restored. A failed audit entry is preserved in the ledger for transparency.
7. **No Arbitrary Shell Command Execution:** Shell injection attempts embedded in proposed code are never passed to bash/powershell/sh.

### 2.2 Execution Workflow
```
[Client Request: RepairApplyRequest]
                |
                v
  Is approval == True?  ---------(No)---------> [Return REJECTED: Approval Required]
                | (Yes)
  Is severity == "low"? ---------(No)---------> [Return REJECTED: Only LOW severity allowed]
                | (Yes)
  Path inside workspace? --------(No)---------> [Return BLOCKED: Path Traversal Blocked]
                | (Yes)
  Read original code & check hash
  Matches expected? ------------(No)---------> [Return CONFLICT: Concurrent Edit Detected]
                | (Yes)
  AST parse proposed code
  Valid syntax? -----------------(No)---------> [Log FAILED in Ledger, Return FAILED]
                | (Yes)
  Write proposed code atomically to disk
                |
  Run Regression Test Suite (pytest)
  Zero regressions? -------------(No)---------> [Restore original code, Log FAILED, Return FAILED]
                | (Yes)
  Record change in Ledger (status='active')
                |
  Return RepairApplyResult (success=True, validation_status='PASSED')
```

---

## 3. Module 7 — Change History & Selective Rollback

### 3.1 Differentiating from Git
Git tracks repository-wide commit snapshots. ArchiteX's audit ledger provides:
- **Issue-Specific Attribution:** Each modification is explicitly linked to an ArchiteX Finding ID (`issue_id`), severity, and author attribution (`AI` vs `User`).
- **Granular Selective Rollback:** Reverts an individual change without needing to roll back an entire multi-file git commit.
- **Strict Conflict Detection:** Before restoring old code, the ledger inspects current file contents on disk. If the file has been edited since the change was applied, ArchiteX detects the conflict and rejects rollback (HTTP 409) rather than clobbering newer developer changes.
- **Post-Rollback Validation:** Restored code is validated for syntax before committing the rollback. If the restored code is invalid, the file is restored to its pre-rollback state.

### 3.2 Database Schema & Safe Migration
The SQLite database resides at `backend/ledger.db`. Database migrations use `PRAGMA table_info` to inspect existing columns and run `ALTER TABLE ledger ADD COLUMN ...` dynamically, ensuring 100% backward compatibility with pre-existing database rows.

#### SQLite Table Definition:
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique incremental change identifier |
| `timestamp` | TEXT | NOT NULL | ISO-8601 UTC timestamp of change |
| `file_path` | TEXT | NOT NULL | Normalized file path |
| `previous_code` | TEXT | NOT NULL DEFAULT '' | Original code before modification |
| `new_code` | TEXT | NOT NULL DEFAULT '' | Code applied by AI or User |
| `severity` | TEXT | NOT NULL DEFAULT 'low' | Severity level ('low', 'medium', 'high') |
| `changed_by` | TEXT | NOT NULL DEFAULT 'AI' | Author type ('AI' or 'User') |
| `details` | TEXT | DEFAULT '' | Human-readable explanation or step description |
| `issue_id` | TEXT | DEFAULT NULL | Associated issue/finding identifier |
| `validation_result` | TEXT | DEFAULT NULL | Validation summary (e.g. 'PASSED', test logs) |
| `status` | TEXT | NOT NULL DEFAULT 'active' | Change state ('active', 'rolled_back', 'failed') |
| `rollback_ref` | INTEGER | DEFAULT NULL | ID of target entry if this is a rollback audit log |
| `before_hash` | TEXT | DEFAULT NULL | SHA-256 hash of previous_code |
| `after_hash` | TEXT | DEFAULT NULL | SHA-256 hash of new_code |

### 3.3 Selective Rollback Workflow & Conflict Detection
```
[Client Request: RollbackRequest(id, workspace_root)]
                |
                v
  Entry found in database? ---------(No)---------> [HTTP 404: Not Found]
                | (Yes)
  Status == 'rolled_back'? ---------(Yes)--------> [HTTP 400: Already rolled back]
                | (No)
  Target file within workspace? ----(No)---------> [HTTP 400: Path outside workspace]
                | (Yes)
  Read current file content from disk
  Normalize line endings (\r\n -> \n)
                |
  Does current == recorded new_code?
                |
               (No) -----------------------------> [HTTP 409 Conflict: File modified since change]
                |
               (Yes)
  Atomic write previous_code to disk
                |
  Validate restored file syntax (ast.parse)
  Syntax valid? --------------------(No)---------> [Restore pre-rollback state, HTTP 400]
                | (Yes)
  Update entry status = 'rolled_back'
  Insert rollback audit event (changed_by='User', rollback_ref=id)
                |
  Return updated LedgerEntry
```

---

## 4. API Specification

### 4.1 Automatic Repair Endpoint
`POST /api/repair/apply`

**Request Body (`RepairApplyRequest`):**
```json
{
  "issue_id": "FINDING-LOW-01",
  "file_path": "services/utils.py",
  "severity": "low",
  "proposed_code": "def calculate_total(items):\n    return sum(items)\n",
  "workspace_root": "C:/Projects/ArchiteX/data/workspaces/abc12345/repo",
  "approval": true,
  "original_code_hash": "a1b2c3d4...",
  "expected_original_code": "def calculate_total(items):\n    pass\n"
}
```

**Response Body (`RepairApplyResult`):**
```json
{
  "success": true,
  "issue_id": "FINDING-LOW-01",
  "file_path": "services/utils.py",
  "severity": "low",
  "validation_status": "PASSED",
  "output_logs": "✅ AST Syntax Valid\n🎉 All pytest suite tests PASSED!",
  "rollback_status": "NOT_NEEDED",
  "explanation": "Automatic repair for issue FINDING-LOW-01 successfully applied, validated, and recorded in Smart Ledger (Change #25).",
  "change_id": 25,
  "details": []
}
```

### 4.2 Ledger History Endpoint
`GET /api/ledger`

**Response (`List[LedgerEntry]`):**
Returns all recorded modifications ordered newest to oldest (`ORDER BY id DESC`).

### 4.3 Log Change Endpoint
`POST /api/ledger/log`

**Request Body (`LedgerLogRequest`):**
Records developer or AI changes and writes safely to the workspace file.

### 4.4 Rollback Endpoint
`POST /api/ledger/rollback`

**Request Body (`RollbackRequest`):**
```json
{
  "id": 25,
  "workspace_root": "C:/Projects/ArchiteX/data/workspaces/abc12345/repo"
}
```

**Responses:**
- `200 OK`: Reverted file and updated status to `rolled_back`.
- `400 Bad Request`: Already rolled back or syntax failure on restoration.
- `404 Not Found`: Change ID not found or target file missing.
- `409 Conflict`: Target file modified by newer developer changes; rollback rejected.

---

## 5. Frontend Integration Details

The frontend interfaces (`frontend/src/components/LedgerPanel.tsx` and `frontend/src/components/LedgerHistory.tsx`) have been enhanced to present:
1. **Change ID (`#id`):** Distinct mono-badge identifying the unique change event.
2. **Issue Attribution (`Issue: finding-id`):** Visual tag associating the ledger entry with the detected debt.
3. **Validation Verdict:** Explicit pill displaying `Validation: PASSED` (green) or `Validation: FAILED` (red).
4. **Active / Rolled Back / Failed State:** Differentiated status pills indicating whether the change is active, reverted, or a failed attempt.
5. **Conflict Protection Banner:** When a rollback fails due to concurrent developer modifications, a prominent banner warns:
   > *Rollback Blocked (Conflict Detected): File has newer modifications that would be lost. ArchiteX prevented overwriting your changes.*
6. **Automatic Repair Action:** The "AI Auto-Solve" action in `App.tsx` routes directly to `/api/repair/apply`, ensuring low severity fixes run through approval checks, concurrency checks, and test regression validation before acceptance.

---

## 6. Testing Performed

All 39 unit tests in `backend/tests/` passed:

### Automatic Repair Suite (`test_repair_engine.py`)
- `test_approved_low_severity_repair_succeeds`: Verifies end-to-end execution, AST validation, and ledger insertion.
- `test_medium_severity_automatic_repair_rejected`: Asserts Medium-severity repair is rejected and original code left untouched.
- `test_high_severity_automatic_repair_rejected`: Asserts High-severity repair is rejected.
- `test_missing_approval_rejected`: Verifies missing approval flag blocks application.
- `test_invalid_python_syntax_causes_restoration`: Confirms syntax errors abort application and restore original code.
- `test_failing_tests_cause_restoration`: Confirms failing unit tests trigger atomic restoration of pre-repair code.
- `test_path_traversal_blocked`: Confirms directory traversal attempts (e.g., `../../etc/passwd`) are blocked.
- `test_concurrent_file_modification_detected`: Verifies stale original hash triggers concurrency conflict abort.
- `test_api_repair_apply_endpoint`: Tests `/api/repair/apply` HTTP response contracts.

### Change History & Rollback Suite (`test_ledger_rollback.py`)
- `test_ai_changes_are_recorded`: Verifies AI modification logging with SHA-256 hashes.
- `test_developer_changes_are_recorded`: Verifies user-originated modifications.
- `test_history_retrieval`: Validates reverse-chronological retrieval.
- `test_successful_selective_rollback`: Reverts file safely and inserts audit record with `rollback_ref`.
- `test_already_rolled_back_entries_cannot_be_rolled_back_again`: Rejects second rollback attempts.
- `test_later_developer_edits_cause_rollback_conflict`: Detects newer developer edits and raises `ConflictError`.
- `test_conflict_does_not_overwrite_developer_edits`: Proves that newer developer code is untouched upon conflict.
- `test_invalid_workspace_paths_are_rejected`: Rejects paths escaping workspace containment.
- `test_rollback_validation_failure_restores_pre_rollback_state`: Validates restored code syntax; restores pre-rollback content on failure.
- `test_api_ledger_routes`: Exercises `/api/ledger`, `/api/ledger/log`, `/api/ledger/rollback`, and verifies HTTP 409 conflict code.

---

## 7. Current Limitations & Future Work

### Implemented Now:
- Full Python AST compilation and bytecode verification for every repair and rollback.
- Pytest regression execution with timeout bounds and workspace root isolation.
- SHA-256 concurrency checks and cross-platform line ending normalization (`\r\n` vs `\n`).
- Safe SQLite migrations preserving pre-existing database rows.
- Interactive conflict warning feedback in UI and HTTP 409 conflict status code.

### Future Improvements:
- **Three-way Merge Rollback:** Support semantic 3-way AST merge (e.g. `git merge-file`) to selectively roll back an AI change even if a developer made non-overlapping changes in other functions in the same file.
- **Multi-language Syntax Validation:** Extend beyond Python to parse TypeScript, JavaScript, and Go syntax trees using tree-sitter.
- **Ephemeral Sandbox Test Containers:** Execute test suites inside micro-containers or WebAssembly sandboxes for untrusted repositories.

