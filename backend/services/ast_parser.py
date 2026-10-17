import ast
import io
import tempfile
import zipfile
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "__macosx",
    "node_modules",
    "site-packages",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
}

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_PY_BYTES = 2 * 1024 * 1024


def ingest_zip(zip_bytes: bytes) -> dict:
    """Unzip a Python repo and return a React Flow graph of files, classes, functions, and imports."""
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise ValueError("Zip file is too large (max 50MB).")

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        _safe_extract(zip_bytes, dest)
        return build_graph(_detect_repo_root(dest))


def build_graph(repo_root: Path) -> dict:
    parsed_files: list[dict] = []
    for path in _iter_python_files(repo_root):
        parsed_files.append(_parse_file(path, repo_root))

    file_index = _index_modules(parsed_files)
    nodes: list[dict] = []
    edges: list[dict] = []

    for file_info in parsed_files:
        file_id = _file_id(file_info["path"])
        nodes.append(
            _node(
                file_id,
                kind="file",
                label=Path(file_info["path"]).name,
                data={
                    "path": file_info["path"],
                    "parse_error": file_info.get("parse_error"),
                    "source": file_info.get("source", ""),
                },
            )
        )

        for cls in file_info["classes"]:
            class_id = _class_id(file_info["path"], cls["name"])
            nodes.append(
                _node(
                    class_id,
                    kind="class",
                    label=cls["name"],
                    data={
                        "path": file_info["path"],
                        "lineno": cls["lineno"],
                        "end_lineno": cls["end_lineno"],
                        "bases": cls["bases"],
                        "docstring": cls["docstring"],
                    },
                )
            )
            edges.append(_edge(file_id, class_id, kind="contains", label="contains"))

            for method in cls["methods"]:
                method_id = _func_id(file_info["path"], f"{cls['name']}.{method['name']}")
                nodes.append(_function_node(method_id, file_info["path"], method, parent_class=cls["name"]))
                edges.append(_edge(class_id, method_id, kind="contains", label="method"))

        for func in file_info["functions"]:
            func_id = _func_id(file_info["path"], func["name"])
            nodes.append(_function_node(func_id, file_info["path"], func))
            edges.append(_edge(file_id, func_id, kind="contains", label="defines"))

        for imp in file_info["imports"]:
            target_path = _resolve_import(file_info["path"], imp, file_index)
            if target_path:
                target_id = _file_id(target_path)
            else:
                module_name = _import_module_name(imp)
                if not module_name:
                    continue
                target_id = _module_id(module_name)
                if not any(n["id"] == target_id for n in nodes):
                    nodes.append(
                        _node(
                            target_id,
                            kind="module",
                            label=module_name,
                            data={"external": True, "module": module_name},
                        )
                    )

            imported = imp.get("name") or imp["module"]
            edge_id = f"e:import:{file_id}:{target_id}:{imported}:{imp['lineno']}"
            if any(e["id"] == edge_id for e in edges):
                continue
            edges.append(
                _edge(
                    file_id,
                    target_id,
                    kind="import",
                    label=f"import {imported}",
                    extra_id=edge_id,
                )
            )

    _layout(nodes)
    return {"nodes": nodes, "edges": edges}


def _safe_extract(zip_bytes: bytes, dest: Path) -> None:
    dest = dest.resolve()
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid zip archive.") from exc

    with archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/") or not name:
                continue
            if name.startswith("/") or any(part == ".." for part in Path(name).parts):
                raise ValueError(f"Unsafe path in zip: {info.filename}")

            target = (dest / name).resolve()
            if not str(target).startswith(str(dest)):
                raise ValueError(f"Unsafe path in zip: {info.filename}")

        archive.extractall(dest)


def _detect_repo_root(extracted: Path) -> Path:
    children = [
        path
        for path in extracted.iterdir()
        if path.name not in {".DS_Store"} and path.name.lower() != "__macosx"
    ]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extracted


def _iter_python_files(repo_root: Path):
    for path in repo_root.rglob("*.py"):
        if any(part.lower() in SKIP_DIRS for part in path.parts):
            continue
        if path.stat().st_size > MAX_PY_BYTES:
            continue
        yield path


def _parse_file(path: Path, repo_root: Path) -> dict:
    rel = path.relative_to(repo_root).as_posix()
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        return {
            "path": rel,
            "imports": [],
            "classes": [],
            "functions": [],
            "parse_error": str(exc),
            "source": source,
        }

    imports: list[dict] = []
    classes: list[dict] = []
    functions: list[dict] = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    {
                        "module": alias.name,
                        "name": alias.asname or alias.name,
                        "level": 0,
                        "lineno": node.lineno,
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    imported = node.module or "*"
                else:
                    imported = alias.asname or alias.name
                imports.append(
                    {
                        "module": node.module or "",
                        "name": imported,
                        "level": node.level,
                        "lineno": node.lineno,
                    }
                )
        elif isinstance(node, ast.ClassDef):
            classes.append(
                {
                    "name": node.name,
                    "lineno": node.lineno,
                    "end_lineno": getattr(node, "end_lineno", node.lineno),
                    "bases": [_expr_name(base) for base in node.bases],
                    "docstring": ast.get_docstring(node),
                    "methods": [
                        _function_info(child)
                        for child in node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ],
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_function_info(node))

    return {
        "path": rel,
        "imports": imports,
        "classes": classes,
        "functions": functions,
        "parse_error": None,
        "source": source,
    }


def _function_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    return {
        "name": node.name,
        "lineno": node.lineno,
        "end_lineno": getattr(node, "end_lineno", node.lineno),
        "args": [arg.arg for arg in node.args.args],
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "docstring": ast.get_docstring(node),
        "decorators": [_expr_name(dec) for dec in node.decorator_list],
    }


def _expr_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_expr_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _expr_name(node.func)
    return ast.unparse(node) if hasattr(ast, "unparse") else node.__class__.__name__


def _index_modules(parsed_files: list[dict]) -> dict[str, str]:
    index: dict[str, str] = {}
    for file_info in parsed_files:
        rel = file_info["path"]
        module = rel[:-3] if rel.endswith(".py") else rel
        if module.endswith("/__init__"):
            module = module[: -len("/__init__")]
        dotted = module.replace("/", ".")
        index[dotted] = rel
        index[rel] = rel
    return index


def _resolve_import(source_path: str, imp: dict, file_index: dict[str, str]) -> str | None:
    level = imp.get("level") or 0
    module = imp.get("module") or ""
    name = imp.get("name") or ""

    if level:
        start = Path(source_path).parent
        for _ in range(max(level - 1, 0)):
            start = start.parent
        if module:
            candidate = ".".join([*start.as_posix().split("/"), *module.split(".")]) if start.as_posix() != "." else module
        else:
            candidate = ".".join([*start.as_posix().split("/"), name]) if start.as_posix() != "." else name
        candidate = candidate.replace("/.", "").lstrip(".")
        return _lookup_module(candidate, file_index)

    for candidate in filter(None, [module, f"{module}.{name}" if module and name else "", name]):
        resolved = _lookup_module(candidate, file_index)
        if resolved:
            return resolved
    return None


def _lookup_module(dotted: str, file_index: dict[str, str]) -> str | None:
    dotted = dotted.strip(".")
    if not dotted:
        return None
    if dotted in file_index:
        return file_index[dotted]
    init_key = f"{dotted}.__init__"
    return file_index.get(init_key)


def _import_module_name(imp: dict) -> str:
    return imp.get("module") or imp.get("name") or ""


def _function_node(node_id: str, path: str, func: dict, parent_class: str | None = None) -> dict:
    label = f"{parent_class}.{func['name']}" if parent_class else func["name"]
    if func["is_async"]:
        label = f"async {label}"
    return _node(
        node_id,
        kind="function",
        label=label,
        data={
            "path": path,
            "lineno": func["lineno"],
            "end_lineno": func["end_lineno"],
            "args": func["args"],
            "is_async": func["is_async"],
            "docstring": func["docstring"],
            "decorators": func["decorators"],
            "parent_class": parent_class,
        },
    )


def _node(node_id: str, kind: str, label: str, data: dict) -> dict:
    return {
        "id": node_id,
        "type": kind,
        "position": {"x": 0, "y": 0},
        "data": {"label": label, "kind": kind, **data},
    }


def _edge(source: str, target: str, kind: str, label: str, extra_id: str | None = None) -> dict:
    return {
        "id": extra_id or f"e:{kind}:{source}:{target}",
        "source": source,
        "target": target,
        "type": "smoothstep",
        "label": label,
        "data": {"kind": kind},
    }


def _file_id(path: str) -> str:
    return f"file:{path}"


def _class_id(path: str, name: str) -> str:
    return f"class:{path}:{name}"


def _func_id(path: str, name: str) -> str:
    return f"func:{path}:{name}"


def _module_id(name: str) -> str:
    return f"mod:{name}"


def _layout(nodes: list[dict]) -> None:
    files = [n for n in nodes if n["data"]["kind"] == "file"]
    others = [n for n in nodes if n["data"]["kind"] != "file"]

    cols = max(1, int(len(files) ** 0.5) or 1)
    for index, node in enumerate(files):
        node["position"] = {
            "x": (index % cols) * 360,
            "y": (index // cols) * 520,
        }

    file_positions = {n["data"].get("path"): n["position"] for n in files}
    buckets: dict[str, int] = {}
    for node in others:
        path = node["data"].get("path") or node["data"].get("module") or ""
        origin = file_positions.get(path, {"x": 40, "y": 40})
        offset = buckets.get(path, 0)
        buckets[path] = offset + 1
        node["position"] = {
            "x": origin["x"] + 40,
            "y": origin["y"] + 90 + offset * 70,
        }
