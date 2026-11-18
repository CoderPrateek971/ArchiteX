import os
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from database import ledger
from main import app


class TestLedgerRollback(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_root = Path(self.temp_dir)
        self.db_file = self.workspace_root / "test_ledger.db"
        self.orig_db_env = os.environ.get("ARCHITEX_LEDGER_DB")
        os.environ["ARCHITEX_LEDGER_DB"] = str(self.db_file)
        ledger.init_db(self.db_file)
        self.client = TestClient(app)

    def tearDown(self):
        if self.orig_db_env:
            os.environ["ARCHITEX_LEDGER_DB"] = self.orig_db_env
        else:
            os.environ.pop("ARCHITEX_LEDGER_DB", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ai_changes_are_recorded(self):
        """AI modifications are recorded with metadata and hashes."""
        target = self.workspace_root / "module_ai.py"
        target.write_text("v1 = 1\n", encoding="utf-8")

        entry = ledger.insert_log(
            file_path="module_ai.py",
            previous_code="v1 = 1\n",
            new_code="v1 = 2\n",
            severity="low",
            changed_by="AI",
            details="AI applied optimization",
            issue_id="ISSUE-AI-1",
            validation_result="PASSED",
            workspace_root=str(self.workspace_root),
            write_to_disk=True,
            db_path=self.db_file,
        )

        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.changed_by, "AI")
        self.assertEqual(entry.status, "active")
        self.assertEqual(entry.issue_id, "ISSUE-AI-1")
        self.assertIsNotNone(entry.before_hash)
        self.assertIsNotNone(entry.after_hash)
        self.assertEqual(target.read_text(encoding="utf-8"), "v1 = 2\n")

    def test_developer_changes_are_recorded(self):
        """Developer manual modifications are recorded as User changes."""
        target = self.workspace_root / "module_user.py"
        target.write_text("dev = 'draft'\n", encoding="utf-8")

        entry = ledger.insert_log(
            file_path="module_user.py",
            previous_code="dev = 'draft'\n",
            new_code="dev = 'production'\n",
            severity="medium",
            changed_by="User",
            details="Developer manual fix",
            workspace_root=str(self.workspace_root),
            write_to_disk=True,
            db_path=self.db_file,
        )

        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.changed_by, "User")
        self.assertEqual(entry.severity, "medium")
        self.assertEqual(target.read_text(encoding="utf-8"), "dev = 'production'\n")

    def test_history_retrieval(self):
        """History retrieval returns entries in reverse chronological order."""
        for i in range(3):
            ledger.insert_log(
                file_path=f"file_{i}.py",
                previous_code="",
                new_code=f"x = {i}\n",
                severity="low",
                changed_by="AI",
                workspace_root=str(self.workspace_root),
                db_path=self.db_file,
            )

        logs = ledger.list_logs(db_path=self.db_file)
        self.assertEqual(len(logs), 3)
        self.assertTrue(logs[0].id > logs[1].id > logs[2].id)

        single = ledger.get_entry(logs[0].id, db_path=self.db_file)
        self.assertIsNotNone(single)
        self.assertEqual(single.id, logs[0].id)

    def test_successful_selective_rollback(self):
        """Selective rollback safely reverts the file to its previous state."""
        target = self.workspace_root / "payment.py"
        v1 = "def charge(): return 'v1'\n"
        v2 = "def charge(): return 'v2'\n"
        target.write_text(v1, encoding="utf-8")

        entry = ledger.insert_log(
            file_path="payment.py",
            previous_code=v1,
            new_code=v2,
            severity="low",
            changed_by="AI",
            workspace_root=str(self.workspace_root),
            write_to_disk=True,
            db_path=self.db_file,
        )
        self.assertEqual(target.read_text(encoding="utf-8"), v2)

        # Execute rollback
        rolled_back = ledger.rollback_change(entry.id, workspace_root=str(self.workspace_root), db_path=self.db_file)
        self.assertEqual(rolled_back.status, "rolled_back")
        self.assertEqual(target.read_text(encoding="utf-8"), v1)

        # Audit history preserved: new entry recorded for rollback
        all_logs = ledger.list_logs(db_path=self.db_file)
        self.assertGreaterEqual(len(all_logs), 2)
        latest = all_logs[0]
        self.assertEqual(latest.rollback_ref, entry.id)
        self.assertEqual(latest.changed_by, "User")

    def test_already_rolled_back_entries_cannot_be_rolled_back_again(self):
        """An entry with rolled_back status cannot be rolled back a second time."""
        target = self.workspace_root / "once.py"
        target.write_text("v1\n", encoding="utf-8")

        entry = ledger.insert_log(
            file_path="once.py",
            previous_code="v1\n",
            new_code="v2\n",
            severity="low",
            workspace_root=str(self.workspace_root),
            write_to_disk=True,
            db_path=self.db_file,
        )

        ledger.rollback_change(entry.id, workspace_root=str(self.workspace_root), db_path=self.db_file)

        with self.assertRaises(ValueError) as ctx:
            ledger.rollback_change(entry.id, workspace_root=str(self.workspace_root), db_path=self.db_file)
        self.assertIn("already rolled back", str(ctx.exception).lower())

    def test_later_developer_edits_cause_rollback_conflict(self):
        """Later edits by a developer cause rollback conflict detection and rejection."""
        target = self.workspace_root / "config.py"
        target.write_text("DEBUG = False\n", encoding="utf-8")

        entry = ledger.insert_log(
            file_path="config.py",
            previous_code="DEBUG = False\n",
            new_code="DEBUG = True\n",
            severity="low",
            changed_by="AI",
            workspace_root=str(self.workspace_root),
            write_to_disk=True,
            db_path=self.db_file,
        )

        # Developer edits the file to something else
        dev_code = "DEBUG = True\nVERBOSE = 2\n# Developer custom logic\n"
        target.write_text(dev_code, encoding="utf-8")

        # Rollback should raise ConflictError
        with self.assertRaises(ledger.ConflictError) as ctx:
            ledger.rollback_change(entry.id, workspace_root=str(self.workspace_root), db_path=self.db_file)

        self.assertIn("conflict", str(ctx.exception).lower())

    def test_conflict_does_not_overwrite_developer_edits(self):
        """Conflict rejection never overwrites developer modifications."""
        target = self.workspace_root / "dev_work.py"
        target.write_text("base\n", encoding="utf-8")

        entry = ledger.insert_log(
            file_path="dev_work.py",
            previous_code="base\n",
            new_code="ai_fix\n",
            severity="low",
            workspace_root=str(self.workspace_root),
            write_to_disk=True,
            db_path=self.db_file,
        )

        dev_work = "ai_fix\n# Important uncommitted developer work\ndef feature(): pass\n"
        target.write_text(dev_work, encoding="utf-8")

        try:
            ledger.rollback_change(entry.id, workspace_root=str(self.workspace_root), db_path=self.db_file)
        except ledger.ConflictError:
            pass

        # File must remain completely untouched
        self.assertEqual(target.read_text(encoding="utf-8"), dev_work)

    def test_invalid_workspace_paths_are_rejected(self):
        """Operations with paths outside the workspace boundary are rejected."""
        with self.assertRaises(ValueError) as ctx:
            ledger._resolve_path("../../secrets.env", workspace_root=str(self.workspace_root))
        self.assertIn("outside workspace", str(ctx.exception).lower())

    def test_rollback_validation_failure_restores_pre_rollback_state(self):
        """If restoring previous code produces syntax errors, pre-rollback state is restored."""
        target = self.workspace_root / "syntax_check.py"
        valid_post_change = "def run():\n    return 'valid_v2'\n"
        target.write_text(valid_post_change, encoding="utf-8")

        # Record entry where previous_code has a deliberate syntax error
        invalid_pre_change = "def run(:\n    broken syntax\n"
        entry = ledger.insert_log(
            file_path="syntax_check.py",
            previous_code=invalid_pre_change,
            new_code=valid_post_change,
            severity="low",
            workspace_root=str(self.workspace_root),
            write_to_disk=False,
            db_path=self.db_file,
        )

        with self.assertRaises(ValueError) as ctx:
            ledger.rollback_change(entry.id, workspace_root=str(self.workspace_root), db_path=self.db_file)

        self.assertIn("syntaxerror", str(ctx.exception).lower())
        # Target file must be restored to valid_post_change (pre-rollback state)
        self.assertEqual(target.read_text(encoding="utf-8"), valid_post_change)

    def test_api_ledger_routes(self):
        """API endpoints /api/ledger, /api/ledger/log, and /api/ledger/rollback function cleanly."""
        target = self.workspace_root / "api_test.py"
        target.write_text("initial\n", encoding="utf-8")

        # 1. POST /api/ledger/log
        log_res = self.client.post(
            "/api/ledger/log",
            json={
                "file_path": "api_test.py",
                "previous_code": "initial\n",
                "new_code": "updated\n",
                "severity": "low",
                "changed_by": "AI",
                "details": "API test change",
                "workspace_root": str(self.workspace_root),
            },
        )
        self.assertEqual(log_res.status_code, 200)
        entry_data = log_res.json()
        change_id = entry_data["id"]
        self.assertEqual(entry_data["status"], "active")

        # 2. GET /api/ledger
        get_res = self.client.get("/api/ledger")
        self.assertEqual(get_res.status_code, 200)
        logs = get_res.json()
        self.assertTrue(any(l["id"] == change_id for l in logs))

        # 3. Simulate conflict: developer edits the file
        target.write_text("updated\n# Dev addition\n", encoding="utf-8")
        conflict_res = self.client.post(
            "/api/ledger/rollback",
            json={"id": change_id, "workspace_root": str(self.workspace_root)},
        )
        self.assertEqual(conflict_res.status_code, 409)
        self.assertIn("conflict", conflict_res.json()["detail"].lower())

        # 4. Resolve conflict by matching recorded state and rollback successfully
        target.write_text("updated\n", encoding="utf-8")
        rollback_res = self.client.post(
            "/api/ledger/rollback",
            json={"id": change_id, "workspace_root": str(self.workspace_root)},
        )
        self.assertEqual(rollback_res.status_code, 200)
        self.assertEqual(rollback_res.json()["status"], "rolled_back")
        self.assertEqual(target.read_text(encoding="utf-8"), "initial\n")


if __name__ == "__main__":
    unittest.main()

