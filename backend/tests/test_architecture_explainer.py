import unittest
from services.architecture_explainer import (
    analyze_codebase_architecture,
    answer_codebase_question,
    generate_onboarding_documentation,
)
from services.debt_detector import GraphPayload


class TestArchitectureExplainer(unittest.TestCase):
    def setUp(self):
        self.payload = GraphPayload(
            workspace_id="test_ws_123",
            nodes=[
                {
                    "id": "file:main.py",
                    "type": "file",
                    "data": {
                        "kind": "file",
                        "path": "main.py",
                        "label": "main.py",
                        "docstring": "FastAPI Entry Point for ArchiteX.",
                    },
                },
                {
                    "id": "file:services/scanner.py",
                    "type": "file",
                    "data": {
                        "kind": "file",
                        "path": "services/scanner.py",
                        "label": "scanner.py",
                        "docstring": "Scans directory trees and filters irrelevant files.",
                    },
                },
                {
                    "id": "file:database/ledger.py",
                    "type": "file",
                    "data": {
                        "kind": "file",
                        "path": "database/ledger.py",
                        "label": "ledger.py",
                        "docstring": "Maintains SQLite audit ledger.",
                    },
                },
                {
                    "id": "class:database/ledger.py:LedgerManager",
                    "type": "class",
                    "data": {
                        "kind": "class",
                        "path": "database/ledger.py",
                        "label": "LedgerManager",
                        "bases": ["BaseModel"],
                    },
                },
                {
                    "id": "func:services/scanner.py:scan_repo",
                    "type": "function",
                    "data": {
                        "kind": "function",
                        "path": "services/scanner.py",
                        "label": "scan_repo",
                        "calls": ["LedgerManager"],
                    },
                },
            ],
            edges=[
                {
                    "id": "e:import:file:main.py:file:services/scanner.py",
                    "source": "file:main.py",
                    "target": "file:services/scanner.py",
                    "data": {"kind": "import"},
                },
                {
                    "id": "e:import:file:services/scanner.py:file:database/ledger.py",
                    "source": "file:services/scanner.py",
                    "target": "file:database/ledger.py",
                    "data": {"kind": "import"},
                },
            ],
            files=["main.py", "services/scanner.py", "database/ledger.py"],
            file_map={
                "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "services/scanner.py": "from database.ledger import LedgerManager\ndef scan_repo(): pass\n",
                "database/ledger.py": "import sqlite3\nclass LedgerManager: pass\n",
            },
        )

    def test_analyze_codebase_architecture(self):
        report = analyze_codebase_architecture(self.payload)
        self.assertIsNotNone(report.system_overview)
        self.assertIn("Layered", report.architectural_pattern)
        self.assertGreater(len(report.file_responsibilities), 0)
        self.assertGreater(len(report.data_flow), 0)
        self.assertIn("FastAPI", report.key_technologies)
        self.assertIn("SQLite", report.key_technologies)

        # Check file responsibilities
        paths = [f.file_path for f in report.file_responsibilities]
        self.assertIn("main.py", paths)
        self.assertIn("services/scanner.py", paths)
        self.assertIn("database/ledger.py", paths)

    def test_generate_onboarding_documentation(self):
        doc = generate_onboarding_documentation(self.payload)
        self.assertIn("Onboarding Guide", doc.title)
        self.assertIn("# ", doc.markdown)
        self.assertIn("Data Flow", doc.markdown)
        self.assertIn("File Responsibilities", doc.markdown)
        self.assertIn("main.py", doc.markdown)

    def test_answer_codebase_question(self):
        q = "Where is data stored and how does the ledger work?"
        ans = answer_codebase_question(self.payload, q)
        self.assertIsNotNone(ans.answer)
        self.assertIn("database/ledger.py", ans.relevant_files)
        self.assertIn("LedgerManager", ans.relevant_symbols)


if __name__ == "__main__":
    unittest.main()
