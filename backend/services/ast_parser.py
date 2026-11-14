import ast
import io
import os
import tempfile
import zipfile
from pathlib import Path

from services.project_scanner import (
    IRRELEVANT_DIRS,
    MAX_FILE_BYTES,
    MAX_ZIP_BYTES,
    detect_repo_root,
    extract_zip_archive,
    is_irrelevant_dir,
    is_python_file,
    validate_zip_archive,
)

SKIP_DIRS = IRRELEVANT_DIRS
MAX_PY_BYTES = MAX_FILE_BYTES


def ingest_zip(zip_bytes: bytes) -> dict:
    """Unzip a Python repo and return a React Flow graph of files, classes, functions, and imports."""
    valid, err = validate_zip_archive(zip_bytes)
    if not valid:
        raise ValueError(err or "Invalid zip archive.")

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        repo_root = extract_zip_archive(zip_bytes, dest)
        return build_graph(repo_root)


def build_graph(repo_root: Path, python_files: list[Path] | None = None) -> dict:
    parsed_files: list[dict] = []
    files_to_parse = python_files if python_files is not None else list(_iter_python_files(repo_root))
    for path in files_to_parse:
        parsed_files.append(_parse_file(path, repo_root))

    file_index = _index_modules(parsed_files)
    nodes: list[dict] = []
    edges: list[dict] = []

    # Symbol lookup maps for inheritance and call dependency resolution
    class_symbol_map: dict[str, str] = {}
    func_symbol_map: dict[str, str] = {}

    for file_info in parsed_files:
        for cls in file_info["classes"]:
            class_symbol_map[cls["name"]] = _class_id(file_info["path"], cls["name"])
            class_symbol_map[f"{Path(file_info['path']).stem}.{cls['name']}"] = _class_id(file_info["path"], cls["name"])
            for m in cls["methods"]:
                func_symbol_map[f"{cls['name']}.{m['name']}"] = _func_id(file_info["path"], f"{cls['name']}.{m['name']}")
        for func in file_info["functions"]:
            func_symbol_map[func["name"]] = _func_id(file_info["path"], func["name"])
            func_symbol_map[f"{Path(file_info['path']).stem}.{func['name']}"] = _func_id(file_info["path"], func["name"])

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
                    "docstring": file_info.get("docstring"),
                    "classes_count": len(file_info["classes"]),
                    "functions_count": len(file_info["functions"]),
                    "imports_count": len(file_info["imports"]),
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

            # Class inheritance dependencies
            for base in cls["bases"]:
                base_clean = base.split(".")[-1]
                target_cls_id = class_symbol_map.get(base) or class_symbol_map.get(base_clean)
                if target_cls_id and target_cls_id != class_id:
                    edge_id = f"e:inherits:{class_id}:{target_cls_id}"
                    if not any(e["id"] == edge_id for e in edges):
                        edges.append(_edge(class_id, target_cls_id, kind="inherits", label=f"inherits {base_clean}", extra_id=edge_id))

            for method in cls["methods"]:
                method_id = _func_id(file_info["path"], f"{cls['name']}.{method['name']}")
                nodes.append(_function_node(method_id, file_info["path"], method, parent_class=cls["name"]))
                edges.append(_edge(class_id, method_id, kind="contains", label="method"))

                # Method call dependencies
                for called in method.get("calls", []):
                    called_clean = called.split(".")[-1]
                    target_func_id = (
                        func_symbol_map.get(called)
                        or func_symbol_map.get(called_clean)
                        or class_symbol_map.get(called)
                        or class_symbol_map.get(called_clean)
                    )
                    if target_func_id and target_func_id != method_id:
                        edge_id = f"e:calls:{method_id}:{target_func_id}"
                        if not any(e["id"] == edge_id for e in edges):
                            edges.append(_edge(method_id, target_func_id, kind="calls", label=f"calls {called_clean}", extra_id=edge_id))

        for func in file_info["functions"]:
            func_id = _func_id(file_info["path"], func["name"])
            nodes.append(_function_node(func_id, file_info["path"], func))
            edges.append(_edge(file_id, func_id, kind="contains", label="defines"))

            # Function call dependencies
            for called in func.get("calls", []):
                called_clean = called.split(".")[-1]
                target_func_id = (
                    func_symbol_map.get(called)
                    or func_symbol_map.get(called_clean)
                    or class_symbol_map.get(called)
                    or class_symbol_map.get(called_clean)
                )
                if target_func_id and target_func_id != func_id:
                    edge_id = f"e:calls:{func_id}:{target_func_id}"
                    if not any(e["id"] == edge_id for e in edges):
                        edges.append(_edge(func_id, target_func_id, kind="calls", label=f"calls {called_clean}", extra_id=edge_id))

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
    extract_zip_archive(zip_bytes, dest)


def _detect_repo_root(extracted: Path) -> Path:
    return detect_repo_root(extracted)


def _iter_python_files(repo_root: Path):
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if not is_irrelevant_dir(d)]
        for f in files:
            p = Path(root) / f
            if is_python_file(p):
                try:
                    if p.stat().st_size <= MAX_PY_BYTES:
                        yield p
                except Exception:
                    continue


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
        "docstring": ast.get_docstring(tree),
    }


def _extract_calls(node: ast.AST) -> list[str]:
    calls: list[str] = []
    for subnode in ast.walk(node):
        if isinstance(subnode, ast.Call):
            name = _expr_name(subnode.func)
            if name and name not in calls:
                calls.append(name)
    return calls


def _function_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    return {
        "name": node.name,
        "lineno": node.lineno,
        "end_lineno": getattr(node, "end_lineno", node.lineno),
        "args": [arg.arg for arg in node.args.args],
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "docstring": ast.get_docstring(node),
        "decorators": [_expr_name(dec) for dec in node.decorator_list],
        "calls": _extract_calls(node),
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
            "calls": func.get("calls", []),
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
