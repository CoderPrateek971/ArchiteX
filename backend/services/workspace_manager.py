import io
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from services.ast_parser import _detect_repo_root, _safe_extract, build_graph

WORKSPACES_DIR = Path(__file__).resolve().parent.parent / "data" / "workspaces"


def init_workspace_dir() -> Path:
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    return WORKSPACES_DIR


def create_workspace_from_zip(zip_bytes: bytes) -> dict[str, Any]:
    """Extract zip into a dedicated persistent workspace and return graph + metadata."""
    init_workspace_dir()
    workspace_id = uuid.uuid4().hex[:12]
    workspace_path = WORKSPACES_DIR / workspace_id
    workspace_path.mkdir(parents=True, exist_ok=True)

    dest = workspace_path / "repo"
    dest.mkdir(parents=True, exist_ok=True)

    _safe_extract(zip_bytes, dest)
    repo_root = _detect_repo_root(dest)

    graph = build_graph(repo_root)

    # Collect list of files and their contents
    file_map: dict[str, str] = {}
    for node in graph["nodes"]:
        if node.get("type") == "file" or (node.get("data") or {}).get("kind") == "file":
            rel_path = (node.get("data") or {}).get("path")
            if rel_path:
                full_path = repo_root / rel_path
                if full_path.is_file():
                    try:
                        file_map[rel_path] = full_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        file_map[rel_path] = ""

    return {
        "workspace_id": workspace_id,
        "repo_root": str(repo_root.resolve()),
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "files": list(file_map.keys()),
        "file_map": file_map,
    }


def get_workspace_root(workspace_id: str) -> Path:
    init_workspace_dir()
    workspace_path = WORKSPACES_DIR / workspace_id
    if not workspace_path.exists():
        raise KeyError(f"Workspace {workspace_id} not found.")

    repo_dir = workspace_path / "repo"
    if repo_dir.exists():
        return _detect_repo_root(repo_dir)
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
