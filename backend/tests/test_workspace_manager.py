import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
import subprocess

from services.workspace_manager import (
    create_workspace_from_git,
    create_workspace_from_zip,
    get_workspace_root,
    read_workspace_file,
    write_workspace_file,
    cleanup_workspace,
)


class TestWorkspaceManager(unittest.TestCase):
    def test_create_workspace_from_valid_zip(self):
        """Create workspace from a valid zip archive containing Python files."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("module/app.py", "import os\ndef hello():\n    return 'world'\n")
            z.writestr("module/models.py", "class User:\n    pass\n")
            z.writestr("README.md", "# Test repo")
            z.writestr("node_modules/junk.py", "# should be ignored")

        zip_bytes = buf.getvalue()
        result = create_workspace_from_zip(zip_bytes, "test_repo.zip")

        workspace_id = result.get("workspace_id")
        self.assertIsNotNone(workspace_id)
        try:
            self.assertIn("nodes", result)
            self.assertIn("edges", result)
            self.assertIn("files", result)
            self.assertIn("file_map", result)
            self.assertIn("validation_summary", result)

            summary = result["validation_summary"]
            self.assertTrue(summary["is_valid"])
            self.assertEqual(summary["python_files_count"], 2)
            self.assertIn("module/app.py", result["files"])
            self.assertIn("module/models.py", result["files"])
            self.assertNotIn("node_modules/junk.py", result["files"])

            # Test reading and writing workspace file
            content = read_workspace_file(workspace_id, "module/app.py")
            self.assertIn("def hello():", content)

            write_workspace_file(workspace_id, "module/app.py", "# updated code\ndef hello(): return 'updated'")
            updated = read_workspace_file(workspace_id, "module/app.py")
            self.assertIn("# updated code", updated)
        finally:
            cleanup_workspace(workspace_id)

    def test_create_workspace_from_empty_zip_fails(self):
        """Empty zip should fail validation."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            pass  # empty
        with self.assertRaises(ValueError):
            create_workspace_from_zip(buf.getvalue(), "empty.zip")

    def test_create_workspace_from_non_python_zip_fails(self):
        """Zip with no python files should fail validation with clear message."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("notes.txt", "Some notes")
            z.writestr("image.png", "fake image")

        with self.assertRaises(ValueError) as ctx:
            create_workspace_from_zip(buf.getvalue(), "no_py.zip")
        self.assertIn("No Python files found", str(ctx.exception))

    def test_create_workspace_from_local_git_repo(self):
        """Create a real local git repo and clone it into a workspace."""
        temp_dir = tempfile.mkdtemp()
        try:
            repo_path = Path(temp_dir) / "source_repo"
            repo_path.mkdir()
            subprocess.run(["git", "init"], cwd=str(repo_path), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo_path), check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo_path), check=True)

            (repo_path / "main.py").write_text("class Core:\n    def run(self):\n        pass\n")
            (repo_path / "utils.py").write_text("def helper():\n    return 1\n")
            subprocess.run(["git", "add", "."], cwd=str(repo_path), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo_path), check=True, capture_output=True)

            # Test cloning the local file:// repo
            file_url = f"file://{repo_path.resolve()}"
            result = create_workspace_from_git(file_url)

            workspace_id = result.get("workspace_id")
            self.assertIsNotNone(workspace_id)
            try:
                self.assertIn("nodes", result)
                self.assertIn("files", result)
                self.assertIn("main.py", result["files"])
                self.assertIn("utils.py", result["files"])
                self.assertTrue(result["validation_summary"]["is_valid"])
                self.assertEqual(result["validation_summary"]["python_files_count"], 2)
            finally:
                cleanup_workspace(workspace_id)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

