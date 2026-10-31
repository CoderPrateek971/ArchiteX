import io
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional

from services.ast_parser import build_graph
from services.project_scanner import (
    clone_git_repo,
    detect_repo_root,
    extract_zip_archive,
    scan_and_validate_project,
    validate_git_url,
    validate_zip_archive,
)

WORKSPACES_DIR = Path(__file__).resolve().parent.parent / "data" / "workspaces"


def init_workspace_dir() -> Path:
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    return WORKSPACES_DIR


def create_workspace_from_zip(zip_bytes: bytes, filename: str = "") -> dict[str, Any]:
    """
    Validates, extracts zip into a dedicated persistent workspace,
    filters irrelevant directories, identifies Python files, validates syntax,
    and returns graph + file_map + validation summary.
    """
    init_workspace_dir()

    # 1. Validate ZIP
    is_valid_zip, err = validate_zip_archive(zip_bytes)
    if not is_valid_zip:
        raise ValueError(f"Invalid ZIP archive: {err}")

    workspace_id = uuid.uuid4().hex[:12]
    workspace_path = WORKSPACES_DIR / workspace_id
    workspace_path.mkdir(parents=True, exist_ok=True)

    dest = workspace_path / "repo"
    dest.mkdir(parents=True, exist_ok=True)

    try:
        # 2. Extract securely
        extract_zip_archive(zip_bytes, dest)
        repo_root = detect_repo_root(dest)

        # 3. Filter irrelevant directories, identify Python files, validate syntax
        validation = scan_and_validate_project(repo_root)
        if not validation.is_valid:
            error_details = "; ".join(validation.errors) or "Project validation failed."
            raise ValueError(error_details)

        # 4. Build AST Graph for identified Python files
        valid_py_paths = [repo_root / f.path for f in validation.python_files if f.is_valid_python]
        graph = build_graph(repo_root, python_files=valid_py_paths)

        # 5. Populate file_map
        file_map: dict[str, str] = {}
        for f in validation.python_files:
            full_path = repo_root / f.path
            if full_path.is_file():
                try:
                    file_map[f.path] = full_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    file_map[f.path] = ""

        return {
            "workspace_id": workspace_id,
            "repo_root": str(repo_root.resolve()),
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "files": list(file_map.keys()),
            "file_map": file_map,
            "validation_summary": validation.model_dump(),
        }
    except Exception:
        cleanup_workspace(workspace_id)
        raise


def create_workspace_from_git(git_url: str, branch: Optional[str] = None) -> dict[str, Any]:
    """
    Validates Git URL, shallow clones repo into a dedicated workspace,
    filters irrelevant directories, identifies Python files, validates syntax,
    and returns graph + file_map + validation summary + git_info.
    """
    init_workspace_dir()

    # 1. Validate Git URL
    is_valid_url, err = validate_git_url(git_url)
    if not is_valid_url:
        raise ValueError(f"Invalid Git URL: {err}")

    workspace_id = uuid.uuid4().hex[:12]
    workspace_path = WORKSPACES_DIR / workspace_id
    workspace_path.mkdir(parents=True, exist_ok=True)

    dest = workspace_path / "repo"
    dest.mkdir(parents=True, exist_ok=True)

    try:
        # 2. Clone Git repo safely
        repo_root, git_info = clone_git_repo(git_url, dest, branch=branch)

        # 3. Filter irrelevant directories, identify Python files, validate syntax
        validation = scan_and_validate_project(repo_root)
        if not validation.is_valid:
            error_details = "; ".join(validation.errors) or "Project validation failed."
            raise ValueError(error_details)

        # 4. Build AST Graph for identified Python files
        valid_py_paths = [repo_root / f.path for f in validation.python_files if f.is_valid_python]
        graph = build_graph(repo_root, python_files=valid_py_paths)

        # 5. Populate file_map
        file_map: dict[str, str] = {}
        for f in validation.python_files:
            full_path = repo_root / f.path
            if full_path.is_file():
                try:
                    file_map[f.path] = full_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    file_map[f.path] = ""

        return {
            "workspace_id": workspace_id,
            "repo_root": str(repo_root.resolve()),
            "nodes": graph["nodes"],
            "edges": graph["edges"],
            "files": list(file_map.keys()),
            "file_map": file_map,
            "validation_summary": validation.model_dump(),
            "git_info": git_info,
        }
    except Exception:
        cleanup_workspace(workspace_id)
        raise


def get_workspace_root(workspace_id: str) -> Path:
    init_workspace_dir()
    workspace_path = WORKSPACES_DIR / workspace_id
    if not workspace_path.exists():
        raise KeyError(f"Workspace {workspace_id} not found.")

    repo_dir = workspace_path / "repo"
    if repo_dir.exists():
        return detect_repo_root(repo_dir)
    return workspace_path


def read_workspace_file(workspace_id: str, file_path: str) -> str:
    root = get_workspace_root(workspace_id)
    target = (root / file_path).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise ValueError("Target file is outside the workspace.")
    if not target.is_file():
        raise FileNotFoundError(f"File {file_path} not found in workspace.")
    return target.read_text(encoding="utf-8", errors="replace")


def write_workspace_file(workspace_id: str, file_path: str, content: str) -> Path:
    root = get_workspace_root(workspace_id)
    target = (root / file_path).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise ValueError("Target file is outside the workspace.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def create_workspace_zip(workspace_id: str) -> bytes:
    root = get_workspace_root(workspace_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in root.rglob("*"):
            if file.is_file():
                rel = file.relative_to(root)
                zip_file.write(file, arcname=str(rel))
    buffer.seek(0)
    return buffer.getvalue()


def cleanup_workspace(workspace_id: str) -> None:
    workspace_path = WORKSPACES_DIR / workspace_id
    if workspace_path.exists():
        shutil.rmtree(workspace_path, ignore_errors=True)
