import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field
from services.debt_detector import GraphPayload
from services.llm_router import generate_completion

logger = logging.getLogger(__name__)


# =====================================================================
# Models
# =====================================================================

class FileResponsibility(BaseModel):
    file_path: str
    role: str
    summary: str
    key_classes: list[str] = Field(default_factory=list)
    key_functions: list[str] = Field(default_factory=list)
    imports_internal: list[str] = Field(default_factory=list)
    imports_external: list[str] = Field(default_factory=list)
    dependents: list[str] = Field(default_factory=list)


class DataFlowStep(BaseModel):
    step_number: int
    stage: str
    source: str
    destination: str
    description: str
    files_involved: list[str] = Field(default_factory=list)


class ArchitectureReport(BaseModel):
    project_name: str
    system_overview: str
    architectural_pattern: str
    primary_layers: list[dict[str, Any]] = Field(default_factory=list)
    file_responsibilities: list[FileResponsibility] = Field(default_factory=list)
    data_flow: list[DataFlowStep] = Field(default_factory=list)
    key_technologies: list[str] = Field(default_factory=list)
    model_used: Optional[str] = None
    fallback_used: bool = False


class OnboardingDocResponse(BaseModel):
    title: str
    markdown: str
    project_name: str
    generated_at: str


class AskCodebaseRequest(BaseModel):
    question: str = Field(..., min_length=1)
    graph: GraphPayload


class CodebaseQnAResponse(BaseModel):
    question: str
    answer: str
    relevant_files: list[str] = Field(default_factory=list)
    relevant_symbols: list[str] = Field(default_factory=list)
    model_used: Optional[str] = None
    fallback_used: bool = False


# =====================================================================
# AST-Driven Architectural Analyzer
# =====================================================================

def analyze_codebase_architecture(payload: GraphPayload) -> ArchitectureReport:
    """
    Analyzes the GraphPayload using AST nodes, relationships, and code sources.
    Uses LLM when available, and seamlessly falls back to a deterministic analyzer.
    """
    files_map = _extract_file_catalog(payload)
    dependencies, dependents = _extract_dependency_matrix(payload)
    key_tech = _detect_technologies(payload)
    arch_pattern = _detect_architectural_pattern(files_map, key_tech)
    data_flow = _synthesize_data_flow(files_map, dependencies, dependents)
    file_responsibilities = _build_file_responsibilities(files_map, dependencies, dependents)

    project_name = "Python Project"
    if payload.validation_summary and payload.validation_summary.get("repo_name"):
        project_name = payload.validation_summary["repo_name"]
    elif payload.repo_root:
        project_name = Path(payload.repo_root).name

    # Try LLM synthesis for polished narrative if available
    llm_overview = None
    model_used = None
    fallback_used = False

    try:
        summary_prompt = _build_llm_architecture_prompt(
            project_name=project_name,
            arch_pattern=arch_pattern,
            technologies=key_tech,
            files_map=files_map,
            data_flow=data_flow,
        )
        llm_res = generate_completion(
            summary_prompt,
            system=(
                "You are a senior software architect. Provide a clear, technical, and concise "
                "overview of this codebase's architecture, layers, and operational purpose."
            ),
        )
        if llm_res and llm_res.get("content"):
            llm_overview = llm_res["content"].strip()
            model_used = llm_res.get("model")
            fallback_used = llm_res.get("fallback_used", False)
    except Exception as exc:
        logger.info("LLM architecture generation unavailable (%s). Using deterministic overview.", exc)
        fallback_used = True

    if not llm_overview:
        llm_overview = _generate_deterministic_overview(
            project_name=project_name,
            arch_pattern=arch_pattern,
            key_technologies=key_tech,
            files_map=files_map,
            data_flow=data_flow,
        )

    layers = _organize_into_layers(file_responsibilities)

    return ArchitectureReport(
        project_name=project_name,
        system_overview=llm_overview,
        architectural_pattern=arch_pattern,
        primary_layers=layers,
        file_responsibilities=file_responsibilities,
        data_flow=data_flow,
        key_technologies=key_tech,
        model_used=model_used,
        fallback_used=fallback_used,
    )


# =====================================================================
# Onboarding Documentation Generator
# =====================================================================

def generate_onboarding_documentation(payload: GraphPayload) -> OnboardingDocResponse:
    """Generates a complete, developer-ready ONBOARDING.md document."""
    report = analyze_codebase_architecture(payload)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md_lines: list[str] = [
        f"# {report.project_name} — Developer Onboarding Guide",
        f"*Generated on {timestamp} by ArchiteX Architecture Intelligence*",
        "",
        "## 1. System Overview & Architecture",
        f"**Architectural Pattern:** `{report.architectural_pattern}`",
        "",
        report.system_overview,
        "",
        "### Key Technologies & Libraries",
        ", ".join(f"`{t}`" for t in report.key_technologies) if report.key_technologies else "Standard Python Library",
        "",
        "## 2. Architectural Layers",
    ]

    for layer in report.primary_layers:
        md_lines.append(f"### {layer['name']}")
        md_lines.append(f"{layer['description']}")
        md_lines.append("")
        for f in layer.get("files", []):
            md_lines.append(f"- **`{f['path']}`**: {f['summary']}")
        md_lines.append("")

    md_lines.extend([
        "## 3. Data Flow & Request Lifecycles",
        "The system executes data processing and state transitions through the following pipeline:",
        "",
    ])

    for step in report.data_flow:
        md_lines.append(f"#### Step {step.step_number}: {step.stage}")
        md_lines.append(f"- **From:** `{step.source}` ➔ **To:** `{step.destination}`")
        md_lines.append(f"- **Details:** {step.description}")
        if step.files_involved:
            md_lines.append(f"- **Files Involved:** {', '.join(f'`{f}`' for f in step.files_involved)}")
        md_lines.append("")

    md_lines.extend([
        "## 4. File Responsibilities Catalog",
        "| File Path | Primary Role | Key Symbols | Dependents |",
        "| :--- | :--- | :--- | :--- |",
    ])

    for fr in report.file_responsibilities:
        symbols = ", ".join(fr.key_classes + fr.key_functions)[:50] or "None"
        dependents = ", ".join(fr.dependents)[:40] or "None (Root/Entry)"
        md_lines.append(f"| `{fr.file_path}` | {fr.role} | {symbols} | {dependents} |")

    md_lines.extend([
        "",
        "## 5. Getting Started & Developer Workflow",
        "### Local Setup",
        "```bash",
        "# Clone and set up environment",
        "git clone <repo-url>",
        "cd <repo-folder>",
        "python3 -m venv .venv",
        "source .venv/bin/activate",
        "pip install -r requirements.txt",
        "```",
        "",
        "### Architecture Integrity Guidelines",
        "- **Separation of Concerns:** Keep API endpoints focused on validation and transport, and delegate domain logic to services.",
        "- **Explicit Imports:** Avoid circular dependencies between service modules.",
        "- **Data Integrity:** Ensure file modifications and state transitions are logged in persistence stores.",
    ])

    return OnboardingDocResponse(
        title=f"{report.project_name} Onboarding Guide",
        markdown="\n".join(md_lines),
        project_name=report.project_name,
        generated_at=timestamp,
    )


# =====================================================================
# Codebase Question Answering (Q&A)
# =====================================================================

def answer_codebase_question(payload: GraphPayload, question: str) -> CodebaseQnAResponse:
    """Answers developer questions about the codebase using AST graph context."""
    files_map = _extract_file_catalog(payload)
    dependencies, dependents = _extract_dependency_matrix(payload)

    # 1. Match relevant files and symbols based on question keywords
    relevant_files, relevant_symbols = _find_relevant_context(question, files_map, payload)

    # 2. Extract code snippets and symbol details for matched files
    context_chunks: list[str] = []
    for r_file in relevant_files[:5]:
        info = files_map.get(r_file, {})
        classes_str = ", ".join(info.get("classes", []))
        funcs_str = ", ".join(info.get("functions", []))
        deps_str = ", ".join(dependencies.get(r_file, set()))
        source_snip = (payload.file_map or {}).get(r_file, "")[:1500]

        context_chunks.append(
            f"FILE: {r_file}\n"
            f"Classes: {classes_str}\n"
            f"Functions: {funcs_str}\n"
            f"Imports: {deps_str}\n"
            f"Code Preview:\n{source_snip}\n"
        )

    context_str = "\n---\n".join(context_chunks)

    # 3. Try LLM for intelligent answering
    llm_answer = None
    model_used = None
    fallback_used = False

    try:
        q_prompt = (
            f"You are ArchiteX Codebase Intelligence. Answer the following question about this Python codebase.\n"
            f"Use the provided AST structure and code snippets. Cite specific file paths, classes, and functions.\n\n"
            f"QUESTION: {question}\n\n"
            f"CODEBASE CONTEXT:\n{context_str}\n\n"
            f"Provide a clear, detailed explanation with code references and data flow where relevant."
        )
        llm_res = generate_completion(
            q_prompt,
            system="You are an expert AI code assistant analyzing a Python codebase.",
        )
        if llm_res and llm_res.get("content"):
            llm_answer = llm_res["content"].strip()
            model_used = llm_res.get("model")
            fallback_used = llm_res.get("fallback_used", False)
    except Exception as exc:
        logger.info("LLM Q&A unavailable (%s). Using deterministic answer engine.", exc)
        fallback_used = True

    # 4. Fallback deterministic answer
    if not llm_answer:
        llm_answer = _build_deterministic_answer(
            question=question,
            relevant_files=relevant_files,
            relevant_symbols=relevant_symbols,
            files_map=files_map,
            dependencies=dependencies,
        )

    return CodebaseQnAResponse(
        question=question,
        answer=llm_answer,
        relevant_files=relevant_files,
        relevant_symbols=relevant_symbols,
        model_used=model_used,
        fallback_used=fallback_used,
    )


# =====================================================================
# Internal Helpers & Classification Logic
# =====================================================================

def _extract_file_catalog(payload: GraphPayload) -> dict[str, dict[str, Any]]:
    """Builds a rich catalog of each file with classes, functions, docstrings, imports."""
    files: dict[str, dict[str, Any]] = {}

    for node in payload.nodes:
        data = node.get("data") or {}
        kind = data.get("kind") or node.get("type")
        path = data.get("path")

        if not path:
            continue

        if path not in files:
            files[path] = {
                "classes": [],
                "functions": [],
                "methods": [],
                "docstring": "",
                "imports": [],
                "source": (payload.file_map or {}).get(path, ""),
            }

        if kind == "file":
            files[path]["docstring"] = data.get("docstring") or ""
        elif kind == "class":
            files[path]["classes"].append(data.get("label") or node.get("id"))
        elif kind == "function":
            parent = data.get("parent_class")
            label = data.get("label") or ""
            if parent:
                files[path]["methods"].append(label)
            else:
                files[path]["functions"].append(label)

    return files


def _extract_dependency_matrix(payload: GraphPayload) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Computes file-to-file dependencies (A imports B) and dependents (B is imported by A)."""
    node_to_file: dict[str, str] = {}
    for node in payload.nodes:
        data = node.get("data") or {}
        path = data.get("path")
        if path:
            node_to_file[node["id"]] = path

    dependencies: dict[str, set[str]] = {}
    dependents: dict[str, set[str]] = {}

    for edge in payload.edges:
        src = edge.get("source")
        dst = edge.get("target")
        kind = (edge.get("data") or {}).get("kind") or edge.get("label") or ""

        if src in node_to_file and dst in node_to_file:
            src_file = node_to_file[src]
            dst_file = node_to_file[dst]

            if src_file != dst_file:
                dependencies.setdefault(src_file, set()).add(dst_file)
                dependents.setdefault(dst_file, set()).add(src_file)

    return dependencies, dependents


def _detect_technologies(payload: GraphPayload) -> list[str]:
    """Identifies major frameworks and libraries used across the codebase."""
    tech = set()
    external_modules = set()

    for node in payload.nodes:
        data = node.get("data") or {}
        if data.get("kind") == "module" or data.get("external"):
            mod = data.get("module") or data.get("label") or ""
            if mod:
                external_modules.add(mod.split(".")[0].lower())

    # Map module to tech name
    tech_map = {
        "fastapi": "FastAPI",
        "uvicorn": "Uvicorn",
        "flask": "Flask",
        "django": "Django",
        "sqlite3": "SQLite",
        "sqlalchemy": "SQLAlchemy",
        "pydantic": "Pydantic",
        "litellm": "LiteLLM",
        "openai": "OpenAI API",
        "google": "Google AI / Gemini",
        "pytest": "PyTest",
        "requests": "Requests",
        "httpx": "HTTPX",
        "numpy": "NumPy",
        "pandas": "Pandas",
        "torch": "PyTorch",
        "ast": "Python AST Engine",
        "subprocess": "Subprocess CLI",
    }

    for mod, name in tech_map.items():
        if mod in external_modules:
            tech.add(name)

    # Check source text in file_map if external modules list is sparse
    all_sources = " ".join((payload.file_map or {}).values())
    if "FastAPI" in all_sources and "FastAPI" not in tech:
        tech.add("FastAPI")
    if "pydantic" in all_sources and "Pydantic" not in tech:
        tech.add("Pydantic")
    if "sqlite3" in all_sources and "SQLite" not in tech:
        tech.add("SQLite")

    return sorted(list(tech))


def _detect_architectural_pattern(files_map: dict[str, Any], technologies: list[str]) -> str:
    """Determines high-level architectural style from directory structure and frameworks."""
    paths = list(files_map.keys())
    path_str = " ".join(paths).lower()

    if "FastAPI" in technologies or "Flask" in technologies or "Django" in technologies:
        if any("service" in p for p in paths) and any("data" in p or "db" in p or "ledger" in p for p in paths):
            return "Layered Service-Oriented Web API (Controller ➔ Service ➔ Persistence)"
        return "Modern RESTful Micro-Service Architecture"

    if any("cli" in p for p in paths) or "argparse" in path_str or "click" in path_str:
        return "Command Line Interface (CLI) Pipeline Architecture"

    if any("pipeline" in p for p in paths) or any("flow" in p for p in paths):
        return "Data Processing Pipeline Architecture"

    if any("plugin" in p for p in paths):
        return "Extensible Plugin Architecture"

    return "Modular Python Package Architecture"


def _synthesize_data_flow(
    files_map: dict[str, Any],
    dependencies: dict[str, set[str]],
    dependents: dict[str, set[str]],
) -> list[DataFlowStep]:
    """Traces execution and data flow from entry points to processors and storage sinks."""
    steps: list[DataFlowStep] = []
    step_num = 1

    # Stage 1: Ingestion / Entry Points
    entry_files = [
        f for f, info in files_map.items()
        if "main" in f or "app" in f or "server" in f or "cli" in f or not dependents.get(f)
    ]
    if entry_files:
        steps.append(
            DataFlowStep(
                step_number=step_num,
                stage="Request & Ingestion Entry Point",
                source="External Client / User Input",
                destination=entry_files[0],
                description="Receives incoming requests, payload uploads, or CLI arguments and initiates workflow routing.",
                files_involved=entry_files[:3],
            )
        )
        step_num += 1

    # Stage 2: Parsing & Scanning
    scanner_files = [f for f in files_map if "scan" in f or "parser" in f or "extract" in f]
    if scanner_files:
        steps.append(
            DataFlowStep(
                step_number=step_num,
                stage="Parsing, Validation & AST Construction",
                source=entry_files[0] if entry_files else "Entry Point",
                destination=scanner_files[0],
                description="Validates files, filters irrelevant directories, parses code structures into AST representations, and maps symbol dependencies.",
                files_involved=scanner_files,
            )
        )
        step_num += 1

    # Stage 3: Business Logic / Analysis
    service_files = [
        f for f in files_map
        if ("service" in f or "detector" in f or "router" in f or "engine" in f)
        and f not in scanner_files
    ]
    if service_files:
        steps.append(
            DataFlowStep(
                step_number=step_num,
                stage="Core Analysis & Intelligence Processing",
                source=scanner_files[0] if scanner_files else "Workflow",
                destination=service_files[0],
                description="Analyzes structural graphs, detects technical debt, routes queries through LLM providers, and formulates remediation plans.",
                files_involved=service_files[:4],
            )
        )
        step_num += 1

    # Stage 4: Persistence & Storage
    storage_files = [f for f in files_map if "db" in f or "ledger" in f or "store" in f or "data" in f]
    if storage_files:
        steps.append(
            DataFlowStep(
                step_number=step_num,
                stage="Audit Ledger & Workspace Persistence",
                source=service_files[0] if service_files else "Pipeline",
                destination=storage_files[0],
                description="Persists changes, saves workspace trees to disk, and records immutable ledger logs for rollback tracking.",
                files_involved=storage_files,
            )
        )
        step_num += 1

    return steps


def _build_file_responsibilities(
    files_map: dict[str, Any],
    dependencies: dict[str, set[str]],
    dependents: dict[str, set[str]],
) -> list[FileResponsibility]:
    """Generates a detailed responsibility breakdown for each file in the codebase."""
    results: list[FileResponsibility] = []

    for path, info in sorted(files_map.items()):
        path_lower = path.lower()
        role = "Utility / Supporting Module"

        if "main" in path_lower or "app" in path_lower:
            role = "API Gateway & HTTP Controller Routing"
        elif "scanner" in path_lower:
            role = "Directory Filtering & Ingestion Validation"
        elif "parser" in path_lower:
            role = "AST Static Analysis & Dependency Graph Construction"
        elif "debt" in path_lower:
            role = "Technical Debt Detection & Remediation Engine"
        elif "ledger" in path_lower or "db" in path_lower:
            role = "Smart Ledger Persistence & Rollback Audit"
        elif "workspace" in path_lower:
            role = "Workspace File Lifecycle & Sandbox Management"
        elif "llm" in path_lower or "router" in path_lower:
            role = "Multi-LLM Routing & Resilient Fallback Engine"

        # Construct concise summary
        classes = info.get("classes", [])
        funcs = info.get("functions", [])
        summary_parts = []
        if info.get("docstring"):
            summary_parts.append(info["docstring"].splitlines()[0])
        elif classes:
            summary_parts.append(f"Defines core classes: {', '.join(classes[:3])}")
        elif funcs:
            summary_parts.append(f"Provides functional routines: {', '.join(funcs[:4])}")
        else:
            summary_parts.append(f"Handles operations for {Path(path).name}")

        summary = " ".join(summary_parts)

        results.append(
            FileResponsibility(
                file_path=path,
                role=role,
                summary=summary,
                key_classes=classes[:5],
                key_functions=funcs[:6],
                imports_internal=sorted(list(dependencies.get(path, set())))[:6],
                imports_external=[],
                dependents=sorted(list(dependents.get(path, set())))[:6],
            )
        )

    return results


def _organize_into_layers(responsibilities: list[FileResponsibility]) -> list[dict[str, Any]]:
    """Groups files into distinct architectural layers."""
    layers: dict[str, list[dict[str, str]]] = {
        "API & Ingestion Layer": [],
        "Domain & Analysis Services": [],
        "Data & Persistence Layer": [],
        "Infrastructure & Utilities": [],
    }

    for f in responsibilities:
        item = {"path": f.file_path, "role": f.role, "summary": f.summary}
        role_lower = f.role.lower()
        path_lower = f.file_path.lower()

        if "gateway" in role_lower or "ingestion" in role_lower or "main" in path_lower:
            layers["API & Ingestion Layer"].append(item)
        elif "persistence" in role_lower or "ledger" in role_lower or "db" in path_lower or "workspace" in path_lower:
            layers["Data & Persistence Layer"].append(item)
        elif "analysis" in role_lower or "debt" in role_lower or "llm" in role_lower or "service" in path_lower:
            layers["Domain & Analysis Services"].append(item)
        else:
            layers["Infrastructure & Utilities"].append(item)

    return [
        {
            "name": name,
            "description": f"Contains modules and routines governing {name.lower()}.",
            "files": items,
        }
        for name, items in layers.items()
        if items
    ]


def _build_llm_architecture_prompt(
    project_name: str,
    arch_pattern: str,
    technologies: list[str],
    files_map: dict[str, Any],
    data_flow: list[DataFlowStep],
) -> str:
    files_summary = "\n".join(
        f"- {p}: Classes=[{', '.join(info.get('classes', []))}], Funcs=[{', '.join(info.get('functions', []))}]"
        for p, info in list(files_map.items())[:12]
    )
    return (
        f"Project: {project_name}\n"
        f"Architecture Pattern: {arch_pattern}\n"
        f"Key Technologies: {', '.join(technologies)}\n\n"
        f"Files:\n{files_summary}\n\n"
        f"Synthesize a 2-3 paragraph architectural explanation covering: "
        f"1. Core purpose of the system and high-level structure.\n"
        f"2. How components communicate across layers.\n"
        f"3. How data flows through the application."
    )


def _generate_deterministic_overview(
    project_name: str,
    arch_pattern: str,
    key_technologies: list[str],
    files_map: dict[str, Any],
    data_flow: list[DataFlowStep],
) -> str:
    tech_str = ", ".join(key_technologies) if key_technologies else "standard Python libraries"
    total_files = len(files_map)
    total_classes = sum(len(f.get("classes", [])) for f in files_map.values())
    total_funcs = sum(len(f.get("functions", [])) for f in files_map.values())

    flow_desc = " ➔ ".join(step.stage for step in data_flow) if data_flow else "Input ➔ Processing ➔ Output"

    return (
        f"**{project_name}** is built upon a **{arch_pattern}**, comprising {total_files} modules, "
        f"{total_classes} classes, and {total_funcs} functional definitions. "
        f"The application harnesses {tech_str} to structure its operational capabilities.\n\n"
        f"Control flow enters through defined API entry points, where payloads are parsed, "
        f"validated, and mapped into AST dependency structures. Domain services then perform "
        f"static analysis, debt categorization, and AI routing. Finally, state changes and "
        f"audit trails are coordinated through persistent ledger operations.\n\n"
        f"**Core Data Lifecycle:** `{flow_desc}`."
    )


def _find_relevant_context(
    question: str,
    files_map: dict[str, Any],
    payload: GraphPayload,
) -> tuple[list[str], list[str]]:
    """Identifies the most relevant files and symbols matching the user's question."""
    q_words = set(re.findall(r"\w+", question.lower()))
    file_scores: dict[str, int] = {}
    matched_symbols: set[str] = set()

    for path, info in files_map.items():
        score = 0
        path_tokens = set(re.findall(r"\w+", path.lower()))
        score += len(q_words & path_tokens) * 3

        for cls in info.get("classes", []):
            if any(w in cls.lower() for w in q_words):
                score += 4
                matched_symbols.add(cls)

        for func in info.get("functions", []) + info.get("methods", []):
            if any(w in func.lower() for w in q_words):
                score += 3
                matched_symbols.add(func)

        doc = info.get("docstring", "").lower()
        score += sum(1 for w in q_words if w in doc)

        file_scores[path] = score

    sorted_files = [f for f, s in sorted(file_scores.items(), key=lambda x: x[1], reverse=True) if s > 0]
    if not sorted_files:
        sorted_files = list(files_map.keys())[:3]

    return sorted_files[:5], sorted(list(matched_symbols))[:8]


def _build_deterministic_answer(
    question: str,
    relevant_files: list[str],
    relevant_symbols: list[str],
    files_map: dict[str, Any],
    dependencies: dict[str, set[str]],
) -> str:
    """Produces a structured architectural answer based on static code graph mapping."""
    if not relevant_files:
        return (
            "I could not locate specific references matching your query in the current codebase graph. "
            "Try asking about a specific file, class, function, or data flow mechanism."
        )

    lines: list[str] = [
        f"### Codebase Analysis for: *\"{question}\"*",
        "",
        "Based on the static AST dependency graph, here are the key components involved:",
        "",
    ]

    for f in relevant_files:
        info = files_map.get(f, {})
        classes = info.get("classes", [])
        funcs = info.get("functions", [])
        deps = dependencies.get(f, set())

        lines.append(f"#### **`{f}`**")
        if classes:
            lines.append(f"- **Classes:** {', '.join(f'`{c}`' for c in classes)}")
        if funcs:
            lines.append(f"- **Key Functions:** {', '.join(f'`{fn}`' for fn in funcs[:5])}")
        if deps:
            lines.append(f"- **Internal Dependencies:** {', '.join(f'`{d}`' for d in list(deps)[:4])}")
        lines.append("")

    if relevant_symbols:
        lines.append(f"**Identified Symbols:** {', '.join(f'`{s}`' for s in relevant_symbols)}")
        lines.append("")

    lines.append(
        "To explore how these symbols connect visually, select the corresponding nodes in the Knowledge Graph canvas."
    )
    return "\n".join(lines)

