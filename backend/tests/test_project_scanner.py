import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from services.project_scanner import (
    IRRELEVANT_DIRS,
    analyze_python_file,
    detect_repo_root,
    extract_zip_archive,
    is_irrelevant_dir,
    is_python_file,
    matches_gitignore,
    scan_and_validate_project,
    validate_git_url,
    validate_zip_archive,
)


class TestProjectScanner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.root = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_filter_irrelevant_directories(self):
        """Verify irrelevant directories like .git, __pycache__, node_modules, venv are identified."""
        self.assertTrue(is_irrelevant_dir(".git"))
        self.assertTrue(is_irrelevant_dir("__pycache__"))
        self.assertTrue(is_irrelevant_dir("node_modules"))
        self.assertTrue(is_irrelevant_dir(".venv"))
        self.assertTrue(is_irrelevant_dir("venv"))
        self.assertTrue(is_irrelevant_dir(".pytest_cache"))
        self.assertTrue(is_irrelevant_dir(".idea"))
        self.assertTrue(is_irrelevant_dir(".vscode"))
        self.assertTrue(is_irrelevant_dir("my_package.egg-info"))

        # Legitimate source directories should NOT be filtered
        self.assertFalse(is_irrelevant_dir("src"))
        self.assertFalse(is_irrelevant_dir("backend"))
        self.assertFalse(is_irrelevant_dir("services"))
        self.assertFalse(is_irrelevant_dir("utils"))

    def test_gitignore_matching(self):
        """Verify .gitignore patterns match relative paths properly."""
        patterns = ["*.log", "temp/", "/secret.py", "build/*"]
        self.assertTrue(matches_gitignore("debug.log", patterns))
        self.assertTrue(matches_gitignore("sub/deep/app.log", patterns))
        self.assertTrue(matches_gitignore("temp/data.json", patterns))
        self.assertTrue(matches_gitignore("secret.py", patterns))
        self.assertFalse(matches_gitignore("sub/secret.py", patterns))  # because of leading '/'
        self.assertFalse(matches_gitignore("main.py", patterns))

    def test_identify_python_files(self):
        """Verify python file identification by extension and shebang, ignoring non-code files."""
        py_file = self.root / "app.py"
        py_file.write_text("print('hello')")
        self.assertTrue(is_python_file(py_file))

        pyw_file = self.root / "gui.pyw"
        pyw_file.write_text("print('gui')")
        self.assertTrue(is_python_file(pyw_file))

        pyi_file = self.root / "stub.pyi"
        pyi_file.write_text("def test(): ...")
        self.assertTrue(is_python_file(pyi_file))

        # Script with shebang
        script_file = self.root / "cli_runner"
        script_file.write_text("#!/usr/bin/env python3\nprint('cli')")
        self.assertTrue(is_python_file(script_file))

        # Non-python files
        txt_file = self.root / "readme.txt"
        txt_file.write_text("just text")
        self.assertFalse(is_python_file(txt_file))

        png_file = self.root / "logo.png"
        png_file.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertFalse(is_python_file(png_file))

    def test_python_syntax_validation(self):
        """Verify AST parsing identifies valid vs syntax-error files."""
        # Valid python file
        valid_file = self.root / "valid.py"
        valid_file.write_text(
            "import os\n\nclass Sample:\n    def run(self):\n        return True\n"
        )
        valid_info = analyze_python_file(valid_file, self.root)
        self.assertTrue(valid_info.is_valid_python)
        self.assertIsNone(valid_info.syntax_error)
        self.assertEqual(valid_info.classes_count, 1)
        self.assertEqual(valid_info.functions_count, 1)
        self.assertEqual(valid_info.imports_count, 1)
        self.assertEqual(valid_info.lines_of_code, 5)

        # Invalid python file
        broken_file = self.root / "broken.py"
        broken_file.write_text("def missing_colon()\n    pass\n")
        broken_info = analyze_python_file(broken_file, self.root)
        self.assertFalse(broken_info.is_valid_python)
        self.assertIsNotNone(broken_info.syntax_error)
        self.assertEqual(broken_info.syntax_error_lineno, 1)

    def test_scan_and_validate_project(self):
        """Verify full project scan filters irrelevant directories and identifies Python files."""
        # Create project structure:
        # root/
        #   src/
        #     app.py (valid)
        #     helper.py (valid)
        #   node_modules/
        #     ignored.py (should be skipped!)
        #   .venv/
        #     lib.py (should be skipped!)
        #   __pycache__/
        #     cached.py (should be skipped!)
        #   assets/
        #     image.png (should be skipped)
        src_dir = self.root / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("def start():\n    return 42\n")
        (src_dir / "helper.py").write_text("class Helper:\n    pass\n")

        node_dir = self.root / "node_modules" / "some_pkg"
        node_dir.mkdir(parents=True)
        (node_dir / "ignored.py").write_text("print('should be ignored')")

        venv_dir = self.root / ".venv" / "lib"
        venv_dir.mkdir(parents=True)
        (venv_dir / "lib.py").write_text("print('should be ignored')")

        cache_dir = self.root / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "cached.py").write_text("print('should be ignored')")

        assets_dir = self.root / "assets"
        assets_dir.mkdir()
        (assets_dir / "image.png").write_bytes(b"\x89PNG")

        result = scan_and_validate_project(self.root)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.python_files_count, 2)
        self.assertEqual(result.valid_python_files_count, 2)
        self.assertEqual(result.syntax_error_files_count, 0)
        file_paths = [f.path for f in result.python_files]
        self.assertIn("src/app.py", file_paths)
        self.assertIn("src/helper.py", file_paths)
        self.assertNotIn("node_modules/some_pkg/ignored.py", file_paths)
        self.assertNotIn(".venv/lib/lib.py", file_paths)

    def test_scan_project_with_no_python_files(self):
        """Verify validation fails if no Python files are found."""
        (self.root / "readme.md").write_text("# Documentation only")
        (self.root / "styles.css").write_text("body { color: red; }")

        result = scan_and_validate_project(self.root)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.python_files_count, 0)
        self.assertTrue(any("No Python files found" in err for err in result.errors))

    def test_validate_zip_archive_security(self):
        """Verify ZIP validation detects empty, corrupt, or zip slip files."""
        # Empty zip
        valid, err = validate_zip_archive(b"")
        self.assertFalse(valid)
        self.assertIn("empty", err.lower())

        # Non-zip data
        valid, err = validate_zip_archive(b"NOT_A_ZIP_FILE")
        self.assertFalse(valid)

        # Valid zip
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("main.py", "print('hello')")
        valid, err = validate_zip_archive(buf.getvalue())
        self.assertTrue(valid)
        self.assertIsNone(err)

        # Zip Slip attempt
        slip_buf = io.BytesIO()
        with zipfile.ZipFile(slip_buf, "w") as z:
            z.writestr("../../../etc/passwd", "malicious")
        valid, err = validate_zip_archive(slip_buf.getvalue())
        self.assertFalse(valid)
        self.assertIn("traversal", err.lower())

    def test_validate_git_url(self):
        """Verify Git URL validation rejects dangerous options/injections and accepts valid URLs."""
        # Valid URLs
        self.assertTrue(validate_git_url("https://github.com/psf/requests.git")[0])
        self.assertTrue(validate_git_url("http://gitlab.com/user/project")[0])
        self.assertTrue(validate_git_url("git@github.com:torvalds/linux.git")[0])
        self.assertTrue(validate_git_url("git://github.com/fastapi/fastapi")[0])

        # Flag injection attempts
        self.assertFalse(validate_git_url("--upload-pack=evil")[0])
        self.assertFalse(validate_git_url("-u")[0])

        # Shell command injection attempts
        self.assertFalse(validate_git_url("https://github.com/repo; rm -rf /")[0])
        self.assertFalse(validate_git_url("https://github.com/repo && evil")[0])
        self.assertFalse(validate_git_url("https://github.com/repo | evil")[0])
        self.assertFalse(validate_git_url("https://github.com/`id`")[0])
        self.assertFalse(validate_git_url("")[0])


if __name__ == "__main__":
    unittest.main()
