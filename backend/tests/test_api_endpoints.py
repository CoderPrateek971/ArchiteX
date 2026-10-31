import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
from main import app
from services.workspace_manager import cleanup_workspace


class TestApiEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.created_workspaces = []

    def tearDown(self):
        for wid in self.created_workspaces:
            cleanup_workspace(wid)

    def test_upload_valid_zip(self):
        """Test uploading a valid Python repo zip file."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("core.py", "def add(a, b):\n    return a + b\n")
            z.writestr("models.py", "class Item:\n    pass\n")
            z.writestr(".venv/lib.py", "junk")

        response = self.client.post(
            "/api/upload-repo",
            files={"file": ("repo.zip", buf.getvalue(), "application/zip")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("workspace_id", data)
        self.created_workspaces.append(data["workspace_id"])

        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertIn("files", data)
        self.assertIn("core.py", data["files"])
        self.assertIn("models.py", data["files"])
        self.assertNotIn(".venv/lib.py", data["files"])

        # Check validation summary
        self.assertIn("validation_summary", data)
        summary = data["validation_summary"]
        self.assertTrue(summary["is_valid"])
        self.assertEqual(summary["python_files_count"], 2)
        self.assertEqual(summary["valid_python_files_count"], 2)

    def test_upload_non_zip_file_rejected(self):
        """Test uploading a non-zip file returns 400."""
        response = self.client.post(
            "/api/upload-repo",
            files={"file": ("code.py", b"print(1)", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("upload a .zip file", response.json()["detail"].lower())

    def test_upload_zip_with_no_python_files_rejected(self):
        """Test uploading a zip with no Python files returns 400 validation error."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("readme.txt", "No python here")
            z.writestr("styles.css", "body {}")

        response = self.client.post(
            "/api/upload-repo",
            files={"file": ("no_py.zip", buf.getvalue(), "application/zip")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("no python files found", response.json()["detail"].lower())

    def test_clone_invalid_git_url_rejected(self):
        """Test cloning with invalid URL or injection attempts returns 400."""
        # Option flag injection
        res1 = self.client.post("/api/clone-repo", json={"url": "--upload-pack=evil"})
        self.assertEqual(res1.status_code, 400)

        # Shell character injection
        res2 = self.client.post("/api/clone-repo", json={"url": "https://github.com/repo; rm -rf /"})
        self.assertEqual(res2.status_code, 400)

        # Empty URL
        res3 = self.client.post("/api/clone-repo", json={"url": "   "})
        self.assertEqual(res3.status_code, 400)

    def test_clone_local_git_repo(self):
        """Test cloning a local git repository through /api/clone-repo endpoint."""
        temp_dir = tempfile.mkdtemp()
        try:
            repo_path = Path(temp_dir) / "test_git_repo"
            repo_path.mkdir()
            subprocess.run(["git", "init"], cwd=str(repo_path), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo_path), check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo_path), check=True)

            (repo_path / "server.py").write_text("class Server:\n    def start(self):\n        pass\n")
            subprocess.run(["git", "add", "."], cwd=str(repo_path), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo_path), check=True, capture_output=True)

            file_url = f"file://{repo_path.resolve()}"
            response = self.client.post("/api/clone-repo", json={"url": file_url})
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertIn("workspace_id", data)
            self.created_workspaces.append(data["workspace_id"])
            self.assertIn("server.py", data["files"])
            self.assertIn("git_info", data)
            self.assertEqual(data["validation_summary"]["python_files_count"], 1)

            # Test workspace file content endpoint
            wid = data["workspace_id"]
            file_res = self.client.get(f"/api/workspace/{wid}/file?path=server.py")
            self.assertEqual(file_res.status_code, 200)
            self.assertIn("class Server:", file_res.json()["content"])

            # Test explain architecture endpoint
            arch_res = self.client.post("/api/explain-architecture", json=data)
            self.assertEqual(arch_res.status_code, 200)
            arch_json = arch_res.json()
            self.assertIn("architectural_pattern", arch_json)
            self.assertIn("file_responsibilities", arch_json)

            # Test generate onboarding endpoint
            onboard_res = self.client.post("/api/generate-onboarding", json=data)
            self.assertEqual(onboard_res.status_code, 200)
            onboard_json = onboard_res.json()
            self.assertIn("markdown", onboard_json)

            # Test ask codebase endpoint
            ask_res = self.client.post("/api/ask-codebase", json={"question": "What does server.py do?", "graph": data})
            self.assertEqual(ask_res.status_code, 200)
            ask_json = ask_res.json()
            self.assertIn("answer", ask_json)
            self.assertIn("server.py", ask_json["relevant_files"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
