import ast
import fnmatch
import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

# Maximum thresholds for safety
MAX_ZIP_BYTES = 100 * 1024 * 1024       # 100 MB max zip upload
MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024 # 300 MB max uncompressed extraction
MAX_ZIP_FILES = 15000                   # 15,000 files max in an archive
MAX_FILE_BYTES = 2 * 1024 * 1024        # 2 MB max per Python file for AST parsing

# Irrelevant directories to skip during scanning and extraction
IRRELEVANT_DIRS: set[str] = {
    # Version control
    ".git",
    ".hg",
    ".svn",
    ".bzr",
    "_darcs",
    "CVS",
    # Virtual environments & package managers
    ".venv",
    "venv",
    "env",
    ".env",
    "virtualenv",
    "site-packages",
    ".conda",
    "pip-wheel-metadata",
    # Python caches & build artifacts
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".hypothesis",
    "build",
    "dist",
    "eggs",
    ".eggs",
    "htmlcov",
    ".coverage",
    # Web / Node / Frontend artifacts
    "node_modules",
    ".next",
    ".nuxt",
    "bower_components",
    "out",
    ".parcel-cache",
    # IDEs, OS files & general caches
    ".idea",
    ".vscode",
    ".vs",
    ".DS_Store",
    "__MACOSX",
    "thumbs.db",
    ".cache",
    "tmp",
    "temp",
}

# Non-code extensions to skip immediately
IGNORED_FILE_EXTENSIONS: set[str] = {
    # Compiled & binary
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin", ".o", ".a",
    # Media & Images
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".mp3", ".mp4", ".mov", ".wav",
    # Documents & Data archives
    ".pdf", ".docx", ".xlsx", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    # Databases
    ".db", ".sqlite", ".sqlite3",
}

PYTHON_EXTENSIONS: set[str] = {".py", ".pyw", ".pyi"}
SHEBANG_PYTHON_REGEX = re.compile(r"^#!\s*(?:/usr/bin/env\s+python|/usr/bin/python[0-9.]*|/usr/local/bin/python[0-9.]*)")
SAFE_GIT_URL_REGEX = re.compile(
    r"^(?:https?|git|ssh)://[^\s/$.?#].[^\s]*$|^git@[a-zA-Z0-9._-]+:[a-zA-Z0-9._/-]+(?:\.git)?$"
)


# =====================================================================
# Models
# =====================================================================

class ScannedFileInfo(BaseModel):
    path: str  # relative posix path
    size_bytes: int
    lines_of_code: int = 0
    blank_lines: int = 0
    comment_lines: int = 0
    is_valid_python: bool = True
    syntax_error: Optional[str] = None
    syntax_error_lineno: Optional[int] = None
    syntax_error_offset: Optional[int] = None
    classes_count: int = 0
    functions_count: int = 0
    imports_count: int = 0


class ProjectValidationResult(BaseModel):
    is_valid: bool
    repo_name: str
    total_files_scanned: int = 0
    total_directories_scanned: int = 0
    ignored_directories_count: int = 0
    python_files_count: int = 0
    valid_python_files_count: int = 0
    syntax_error_files_count: int = 0
    total_loc: int = 0
    python_files: list[ScannedFileInfo] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# =====================================================================
# Directory Filtering & Gitignore Support
# =====================================================================

def is_irrelevant_dir(dir_name: str) -> bool:
    """Check if a directory name matches known irrelevant or artifact directories."""
    clean_name = dir_name.lower().strip()
    if clean_name in {d.lower() for d in IRRELEVANT_DIRS}:
        return True
    if clean_name.endswith(".egg-info") or clean_name.endswith(".dist-info"):
        return True
    # Ignore any hidden directory (starts with dot)
    if clean_name.startswith(".") and clean_name not in {".", ".."}:
        return True
    return False


def load_gitignore_patterns(repo_root: Path) -> list[str]:
    """Load and parse patterns from .gitignore if present in repo root."""
    gitignore_path = repo_root / ".gitignore"
    patterns: list[str] = []
    if not gitignore_path.is_file():
        return patterns

    try:
        content = gitignore_path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    except Exception:
        pass
    return patterns


def matches_gitignore(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any .gitignore pattern."""
    normalized = rel_path.replace("\\", "/").strip("/")
    parts = normalized.split("/")

    for pattern in patterns:
        pat = pattern.replace("\\", "/").rstrip("/")
        # If pattern starts with '/', match against full relative path
        if pat.startswith("/"):
            if fnmatch.fnmatch(normalized, pat.lstrip("/")):
                return True
        else:
            # Match against filename or any subpath
            if fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(parts[-1], pat):
                return True
            for part in parts:
                if fnmatch.fnmatch(part, pat):
                    return True
    return False


# =====================================================================
# Python File Identification & Validation
# =====================================================================

def is_python_file(file_path: Path) -> bool:
    """Identify if a file is a Python file by extension or shebang."""
    suffix = file_path.suffix.lower()
    if suffix in PYTHON_EXTENSIONS:
        return True

    if suffix in IGNORED_FILE_EXTENSIONS:
        return False

    # For extensionless files or scripts, inspect first line for Python shebang
    if not suffix and file_path.is_file():
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline(256)
                if SHEBANG_PYTHON_REGEX.match(first_line.strip()):
                    return True
        except Exception:
            return False

    return False


def analyze_python_file(file_path: Path, repo_root: Path) -> ScannedFileInfo:
    """Analyze and validate a single Python file using AST parsing."""
    rel_path = file_path.relative_to(repo_root).as_posix()
    size_bytes = file_path.stat().st_size

    if size_bytes > MAX_FILE_BYTES:
        return ScannedFileInfo(
            path=rel_path,
            size_bytes=size_bytes,
            lines_of_code=0,
            is_valid_python=False,
            syntax_error=f"File exceeds maximum size limit ({size_bytes // 1024} KB > {MAX_FILE_BYTES // 1024} KB). Skipped for safety.",
        )

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return ScannedFileInfo(
            path=rel_path,
            size_bytes=size_bytes,
            is_valid_python=False,
            syntax_error=f"Unable to read file: {exc}",
        )

    # Count lines: total, blank, comments
    lines = source.splitlines()
    total_loc = len(lines)
    blank_lines = 0
    comment_lines = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_lines += 1
        elif stripped.startswith("#"):
            comment_lines += 1

    # AST syntax validation
    classes_count = 0
    functions_count = 0
    imports_count = 0
    syntax_error = None
    syntax_lineno = None
    syntax_offset = None
    is_valid = True

    try:
        tree = ast.parse(source, filename=rel_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes_count += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions_count += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                imports_count += 1
    except SyntaxError as exc:
        is_valid = False
        syntax_error = f"{exc.msg} (line {exc.lineno})"
        syntax_lineno = exc.lineno
        syntax_offset = exc.offset
    except Exception as exc:
        is_valid = False
        syntax_error = f"Parse error: {exc}"

    return ScannedFileInfo(
        path=rel_path,
        size_bytes=size_bytes,
        lines_of_code=total_loc,
        blank_lines=blank_lines,
        comment_lines=comment_lines,
        is_valid_python=is_valid,
        syntax_error=syntax_error,
        syntax_error_lineno=syntax_lineno,
        syntax_error_offset=syntax_offset,
        classes_count=classes_count,
        functions_count=functions_count,
        imports_count=imports_count,
    )


# =====================================================================
# Project Scanning & Validation Engine
# =====================================================================

def scan_and_validate_project(repo_root: Path) -> ProjectValidationResult:
    """
    Traverses the repository:
    1. Prunes irrelevant directories (.git, .venv, node_modules, caches, etc.)
    2. Respects .gitignore rules
    3. Identifies and validates all Python files via AST parsing
    4. Produces a structured validation summary
    """
    repo_root = repo_root.resolve()
    repo_name = repo_root.name

    if not repo_root.exists() or not repo_root.is_dir():
        return ProjectValidationResult(
            is_valid=False,
            repo_name=repo_name,
            errors=[f"Directory does not exist or is not a directory: {repo_root}"],
        )

    gitignore_patterns = load_gitignore_patterns(repo_root)

    total_files = 0
    total_dirs = 0
    ignored_dirs = 0
    python_files: list[ScannedFileInfo] = []
    warnings: list[str] = []
    errors: list[str] = []

    # Efficient directory traversal with top-level pruning
    for root_dir, dirs, files in os.walk(repo_root, topdown=True):
        total_dirs += len(dirs)
        current_path = Path(root_dir)
        rel_root = current_path.relative_to(repo_root).as_posix()

        # Prune ignored directories in-place so os.walk does NOT descend into them
        kept_dirs = []
        for d in dirs:
            dir_rel = f"{rel_root}/{d}".strip("/") if rel_root != "." else d
            if is_irrelevant_dir(d) or (gitignore_patterns and matches_gitignore(dir_rel, gitignore_patterns)):
                ignored_dirs += 1
            else:
                kept_dirs.append(d)
        dirs[:] = kept_dirs

        # Process files in current directory
        for f in files:
            file_path = current_path / f
            file_rel = f"{rel_root}/{f}".strip("/") if rel_root != "." else f
            total_files += 1

            if gitignore_patterns and matches_gitignore(file_rel, gitignore_patterns):
                continue

            if is_python_file(file_path):
                file_info = analyze_python_file(file_path, repo_root)
                python_files.append(file_info)
                if not file_info.is_valid_python and file_info.syntax_error:
                    warnings.append(f"{file_info.path}: {file_info.syntax_error}")

    valid_py_count = sum(1 for f in python_files if f.is_valid_python)
    syntax_error_count = sum(1 for f in python_files if not f.is_valid_python)
    total_loc = sum(f.lines_of_code for f in python_files)

    # Validation verdict
    is_valid = True
    if total_files == 0:
        is_valid = False
        errors.append("The project directory contains no files.")
    elif len(python_files) == 0:
        is_valid = False
        errors.append("No Python files found in the project. ArchiteX requires a repository containing Python (.py) files.")

    return ProjectValidationResult(
        is_valid=is_valid,
        repo_name=repo_name,
        total_files_scanned=total_files,
        total_directories_scanned=total_dirs,
        ignored_directories_count=ignored_dirs,
        python_files_count=len(python_files),
        valid_python_files_count=valid_py_count,
        syntax_error_files_count=syntax_error_count,
        total_loc=total_loc,
        python_files=python_files,
        errors=errors,
        warnings=warnings,
    )


# =====================================================================
# ZIP Extraction & Validation
# =====================================================================

def validate_zip_archive(zip_bytes: bytes) -> tuple[bool, Optional[str]]:
    """
    Validates a ZIP archive:
    - Magic bytes check
    - File size check
    - Zip Slip vulnerability protection (path traversal)
    - Decompression bomb protection (uncompressed size & file count limits)
    """
    if not zip_bytes:
        return False, "Uploaded ZIP file is empty."

    if len(zip_bytes) > MAX_ZIP_BYTES:
        return False, f"ZIP file exceeds maximum upload limit of {MAX_ZIP_BYTES // (1024 * 1024)} MB."

    if not zip_bytes.startswith(b"PK"):
        return False, "Uploaded file does not appear to be a valid ZIP archive."

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        return False, f"Corrupted or invalid ZIP archive: {exc}"

    total_uncompressed = 0
    file_count = 0

    with archive:
        infolist = archive.infolist()
        if not infolist:
            return False, "The ZIP archive contains no files."

        for info in infolist:
            file_count += 1
            total_uncompressed += info.file_size

            # Decompression bomb checks
            if file_count > MAX_ZIP_FILES:
                return False, f"ZIP archive contains too many files (limit: {MAX_ZIP_FILES})."
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                return False, f"Uncompressed ZIP size exceeds safe limit ({MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB)."

            # Zip Slip / Path Traversal check
            filename = info.filename.replace("\\", "/")
            if filename.startswith("/") or filename.startswith("\\"):
                return False, f"Insecure path detected in ZIP: {info.filename}"
            if ".." in Path(filename).parts:
                return False, f"Path traversal attempt detected in ZIP: {info.filename}"

    return True, None


def extract_zip_archive(zip_bytes: bytes, dest_dir: Path) -> Path:
    """Safely extracts ZIP contents to dest_dir with path validation."""
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    with archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/") or not name:
                continue
            if name.startswith("/") or any(part == ".." for part in Path(name).parts):
                raise ValueError(f"Unsafe path in zip: {info.filename}")

            target = (dest_dir / name).resolve()
            if not str(target).startswith(str(dest_dir)):
                raise ValueError(f"Unsafe path in zip: {info.filename}")

        archive.extractall(dest_dir)

    return detect_repo_root(dest_dir)


def detect_repo_root(extracted_dir: Path) -> Path:
    """
    If the extracted archive contains a single top-level container directory
    (e.g., 'myrepo-main/'), return that inner folder as the repo root.
    """
    children = [
        path
        for path in extracted_dir.iterdir()
        if path.name not in {".DS_Store", "__MACOSX"} and not path.name.startswith("._")
    ]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extracted_dir


# =====================================================================
# Git Repository Cloning & Validation
# =====================================================================

def validate_git_url(url: str) -> tuple[bool, Optional[str]]:
    """
    Validates a Git URL:
    - Rejects dangerous command injection flags (e.g. starting with '-' or '--')
    - Rejects shell metacharacters
    - Ensures valid URL format (HTTPS, HTTP, SSH, Git)
    """
    url = url.strip()
    if not url:
        return False, "Git repository URL cannot be empty."

    # Prevent git command-line flag injection
    if url.startswith("-"):
        return False, "Invalid repository URL: cannot start with a hyphen or option flag."

    # Prevent shell injection characters
    dangerous_chars = {";", "&", "|", "`", "$", "<", ">", "\n", "\r", "\t", '"', "'"}
    if any(char in url for char in dangerous_chars):
        return False, "Invalid repository URL: contains disallowed characters."

    # Validate scheme or SCP syntax
    is_valid_scheme = (
        url.startswith("https://")
        or url.startswith("http://")
        or url.startswith("git://")
        or url.startswith("ssh://")
        or url.startswith("file://")
        or url.startswith("git@")
    )
    if not is_valid_scheme:
        return False, "Repository URL must start with https://, http://, git://, ssh://, or git@."

    return True, None


def clone_git_repo(
    url: str,
    dest_dir: Path,
    branch: Optional[str] = None,
    timeout_seconds: int = 60,
) -> tuple[Path, dict[str, Any]]:
    """
    Safely clones a Git repository into dest_dir:
    - Uses shallow clone (--depth 1) for speed and disk conservation
    - Handles branch / tag selection
    - Captures commit hash and branch metadata
    - Times out after timeout_seconds
    """
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    is_valid, err = validate_git_url(url)
    if not is_valid:
        raise ValueError(err)

    # Build safe command list (never shell=True)
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        clean_branch = branch.strip()
        if clean_branch.startswith("-") or any(c in clean_branch for c in ";&|`$ \t\n"):
            raise ValueError(f"Invalid branch name: '{branch}'")
        cmd.extend(["--branch", clean_branch])

    cmd.extend([url, str(dest_dir)])

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Git clone timed out after {timeout_seconds} seconds.") from exc
    except Exception as exc:
        raise ValueError(f"Failed to execute git clone: {exc}") from exc

    if result.returncode != 0:
        err_msg = result.stderr.strip() or result.stdout.strip() or f"git clone exited with code {result.returncode}"
        # Sanitize error message to prevent token/credential leak if present in URL
        sanitized_err = re.sub(r"://[^@]+@", "://***@", err_msg)
        raise ValueError(f"Git clone failed: {sanitized_err}")

    # Collect Git metadata
    git_info: dict[str, Any] = {"url": url, "branch": branch}
    try:
        rev_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(dest_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if rev_res.returncode == 0:
            git_info["commit"] = rev_res.stdout.strip()

        branch_res = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(dest_dir),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch_res.returncode == 0 and branch_res.stdout.strip():
            git_info["branch"] = branch_res.stdout.strip()
    except Exception:
        pass

    repo_root = detect_repo_root(dest_dir)
    return repo_root, git_info
