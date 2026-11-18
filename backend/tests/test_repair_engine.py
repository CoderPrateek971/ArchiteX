import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from database import ledger
from main import app
from services.repair_engine import (
    RepairApplyRequest,
    RepairApplyResult,
    apply_automatic_repair,
    apply_repair_request,
)


class TestRepairEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_root = Path(self.temp_dir)
        # Use an isolated test database
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

    def test_approved_low_severity_repair_succeeds(self):
        """Approved low-severity repair succeeds and updates file and ledger."""
        target = self.workspace_root / "service.py"
        target.write_text("def calculate_tax(amount):\n    return amount * 0.1\n", encoding="utf-8")

        new_code = "def calculate_tax(amount):\n    # [Fixed] Explicit rounding\n    return round(amount * 0.1, 2)\n"
        res = apply_automatic_repair(
            issue_id="ISSUE-LOW-01",
            file_path="service.py",
            severity="low",
            proposed_code=new_code,
            workspace_root=str(self.workspace_root),
            approval=True,
        )

        self.assertTrue(res.success)
        self.assertEqual(res.validation_status, "PASSED")
        self.assertEqual(res.rollback_status, "NOT_NEEDED")
        self.assertEqual(target.read_text(encoding="utf-8"), new_code)
        self.assertIsNotNone(res.change_id)

        # Check ledger entry was recorded
        entry = ledger.get_entry(res.change_id, db_path=self.db_file)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, "active")
        self.assertEqual(entry.severity, "low")
        self.assertEqual(entry.changed_by, "AI")
        self.assertEqual(entry.issue_id, "ISSUE-LOW-01")

    def test_medium_severity_automatic_repair_rejected(self):
        """Medium-severity automatic repair is rejected with clear explanation."""
        target = self.workspace_root / "auth.py"
        target.write_text("def auth(): return True\n", encoding="utf-8")

        res = apply_automatic_repair(
            issue_id="ISSUE-MED-01",
            file_path="auth.py",
            severity="medium",
            proposed_code="def auth(): return False\n",
            workspace_root=str(self.workspace_root),
            approval=True,
        )

        self.assertFalse(res.success)
        self.assertEqual(res.validation_status, "REJECTED")
        self.assertEqual(res.rollback_status, "NOT_APPLICABLE")
        self.assertIn("strictly restricted to LOW severity", res.explanation)
        self.assertEqual(target.read_text(encoding="utf-8"), "def auth(): return True\n")

    def test_high_severity_automatic_repair_rejected(self):
        """High-severity automatic repair is rejected with clear explanation."""
        target = self.workspace_root / "database.py"
        target.write_text("def connect(): pass\n", encoding="utf-8")

        res = apply_automatic_repair(
            issue_id="ISSUE-HIGH-01",
            file_path="database.py",
            severity="high",
            proposed_code="def connect(): return None\n",
            workspace_root=str(self.workspace_root),
            approval=True,
        )

        self.assertFalse(res.success)
        self.assertEqual(res.validation_status, "REJECTED")
        self.assertEqual(res.rollback_status, "NOT_APPLICABLE")
        self.assertIn("strictly restricted to LOW severity", res.explanation)
        self.assertEqual(target.read_text(encoding="utf-8"), "def connect(): pass\n")

    def test_missing_approval_rejected(self):
        """Missing explicit approval rejects automatic repair."""
        target = self.workspace_root / "utils.py"
        target.write_text("x = 1\n", encoding="utf-8")

        res = apply_automatic_repair(
            issue_id="ISSUE-NOAPP-01",
            file_path="utils.py",
            severity="low",
            proposed_code="x = 2\n",
            workspace_root=str(self.workspace_root),
            approval=False,
        )

        self.assertFalse(res.success)
        self.assertEqual(res.validation_status, "REJECTED")
        self.assertIn("Explicit approval is required", res.explanation)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 1\n")

    def test_invalid_python_syntax_causes_restoration(self):
        """Invalid Python syntax in proposed code causes automatic restoration."""
        target = self.workspace_root / "parser.py"
        original = "def parse():\n    return {}\n"
        target.write_text(original, encoding="utf-8")

        res = apply_automatic_repair(
            issue_id="ISSUE-SYNTAX-01",
            file_path="parser.py",
            severity="low",
            proposed_code="def broken_syntax(:\n",
            workspace_root=str(self.workspace_root),
            approval=True,
        )

        self.assertFalse(res.success)
        self.assertEqual(res.validation_status, "FAILED")
        self.assertEqual(res.rollback_status, "RESTORED")
        self.assertEqual(target.read_text(encoding="utf-8"), original)

        # Failed attempt is audited in ledger
        self.assertIsNotNone(res.change_id)
        entry = ledger.get_entry(res.change_id, db_path=self.db_file)
        self.assertEqual(entry.status, "failed")

    def test_failing_tests_cause_restoration(self):
        """Failing regression test suite causes automatic restoration of original source."""
        target = self.workspace_root / "calculator.py"
        original = "def add(a, b):\n    return a + b\n"
        target.write_text(original, encoding="utf-8")

        test_file = self.workspace_root / "test_calculator.py"
        test_file.write_text(
            "from calculator import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n",
            encoding="utf-8",
        )

        # Propose broken logic that breaks the unit test
        broken_code = "def add(a, b):\n    return a - b\n"
        res = apply_automatic_repair(
            issue_id="ISSUE-TESTFAIL-01",
            file_path="calculator.py",
            severity="low",
            proposed_code=broken_code,
            workspace_root=str(self.workspace_root),
            approval=True,
        )

        self.assertFalse(res.success)
        self.assertEqual(res.validation_status, "FAILED")
        self.assertEqual(res.rollback_status, "RESTORED")
        self.assertEqual(target.read_text(encoding="utf-8"), original)

        entry = ledger.get_entry(res.change_id, db_path=self.db_file)
        self.assertEqual(entry.status, "failed")

    def test_path_traversal_blocked(self):
        """Path traversal outside workspace root is blocked."""
        res = apply_automatic_repair(
            issue_id="ISSUE-SEC-01",
            file_path="../../etc/passwd",
            severity="low",
            proposed_code="evil = True\n",
            workspace_root=str(self.workspace_root),
            approval=True,
        )

        self.assertFalse(res.success)
        self.assertEqual(res.validation_status, "BLOCKED")
        self.assertIn("Path traversal blocked", res.explanation)

    def test_concurrent_file_modification_detected(self):
        """Concurrency conflict is detected if file changed since fix was generated."""
        target = self.workspace_root / "state.py"
        initial_content = "state = 'initial'\n"
        target.write_text(initial_content, encoding="utf-8")

        original_hash = hashlib.sha256(initial_content.strip().encode("utf-8")).hexdigest()

        # Simulate concurrent developer edit before auto-repair runs
        target.write_text("state = 'modified_by_dev'\n", encoding="utf-8")

        res = apply_automatic_repair(
            issue_id="ISSUE-CONCUR-01",
            file_path="state.py",
            severity="low",
            proposed_code="state = 'ai_repaired'\n",
            workspace_root=str(self.workspace_root),
            approval=True,
            original_code_hash=original_hash,
        )

        self.assertFalse(res.success)
        self.assertEqual(res.validation_status, "CONFLICT")
        self.assertIn("Concurrency conflict", res.explanation)
        # Verify developer's change was NOT overwritten
        self.assertEqual(target.read_text(encoding="utf-8"), "state = 'modified_by_dev'\n")

    def test_api_repair_apply_endpoint(self):
        """API endpoint /api/repair/apply accepts requests and returns structured results."""
        target = self.workspace_root / "api_mod.py"
        target.write_text("def ping(): return 'pong'\n", encoding="utf-8")

        payload = {
            "issue_id": "BUG-API-42",
            "file_path": "api_mod.py",
            "severity": "low",
            "proposed_code": "def ping(): return 'pong-v2'\n",
            "workspace_root": str(self.workspace_root),
            "approval": True,
        }

        response = self.client.post("/api/repair/apply", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["validation_status"], "PASSED")
        self.assertEqual(data["rollback_status"], "NOT_NEEDED")
        self.assertEqual(target.read_text(encoding="utf-8"), "def ping(): return 'pong-v2'\n")


if __name__ == "__main__":
    unittest.main()

