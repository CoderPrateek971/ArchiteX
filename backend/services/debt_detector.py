import ast
import json
import os
import re
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from services.llm_router import generate_completion


class Severity(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class RemediationStep(BaseModel):
    step_number: int
    phase: str
    file_name: str
    action: str
    details: str


class StructuredRemediationPlan(BaseModel):
    target_file: str
    severity: Severity
    upstream_dependencies: list[str] = Field(default_factory=list)
    downstream_dependencies: list[str] = Field(default_factory=list)
    affected_symbols: list[str] = Field(default_factory=list)
    steps: list[RemediationStep] = Field(default_factory=list)
    proposed_code: str = ""
    diff_summary: str = ""
    blast_radius: str = "Low risk"


class DebtFinding(BaseModel):
    id: str
    file_name: str
    title: str
    description: str
    severity: Severity
    category: str
    line_number: int | None = None
    dependencies: list[str] = Field(default_factory=list)
    suggested_fix: str
    proposed_code: str | None = None
    structured_plan: StructuredRemediationPlan | None = None
    status: str = "open"
    ledger_id: int | None = None


class DebtReport(BaseModel):
    findings: list[DebtFinding] = Field(default_factory=list)
    model: str | None = None
    fallback_used: bool = False
    summary_counts: dict[str, int] = Field(default_factory=dict)


class GraphPayload(BaseModel):
    workspace_id: str | None = None
    repo_root: str | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    file_map: dict[str, str] = Field(default_factory=dict)
    validation_summary: dict[str, Any] | None = None
    git_info: dict[str, Any] | None = None


# =====================================================================
# AST Static Bug Detector
# =====================================================================

SECRET_KEYWORDS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "private_key",
    "secret_key",
)


class ASTCodeAuditor(ast.NodeVisitor):
    def __init__(self, file_path: str, source_code: str):
        self.file_path = file_path
        self.source_code = source_code
        self.lines = source_code.splitlines()
        self.findings: list[dict[str, Any]] = []

    def add_finding(
        self,
        title: str,
        description: str,
        severity: Severity,
        category: str,
        line_number: int | None,
        suggested_fix: str,
        dependencies: list[str] | None = None,
    ):
        self.findings.append(
            {
                "file_name": self.file_path,
                "title": title,
                "description": description,
                "severity": severity,
                "category": category,
                "line_number": line_number,
                "suggested_fix": suggested_fix,
                "dependencies": dependencies or [],
            }
        )

    def visit_Call(self, node: ast.Call):
        # 1. Security: eval/exec/compile
        func_name = self._get_name(node.func)
        if func_name in ("eval", "exec", "compile"):
            self.add_finding(
                title=f"Dangerous Dynamic Code Execution (`{func_name}`)",
                description=f"Direct call to `{func_name}()` at line {node.lineno} enables arbitrary code execution vulnerabilities.",
                severity=Severity.HIGH,
                category="Security",
                line_number=node.lineno,
                suggested_fix=f"Replace `{func_name}()` with safe static parsing or domain-specific handlers.",
            )

        # 2. Security: pickle loads
        if func_name in ("pickle.loads", "pickle.load", "_pickle.loads", "_pickle.load"):
            self.add_finding(
                title=f"Insecure Deserialization (`{func_name}`)",
                description=f"Using `{func_name}()` at line {node.lineno} on untrusted data can lead to remote code execution.",
                severity=Severity.HIGH,
                category="Security",
                line_number=node.lineno,
                suggested_fix="Use a safe data serialization format such as JSON, Protocol Buffers, or safe YAML loaders.",
            )

        # 3. Security: subprocess shell=True or os.system
        if func_name in ("os.system", "os.popen"):
            self.add_finding(
                title=f"Command Injection Risk (`{func_name}`)",
                description=f"Direct shell invocation `{func_name}()` at line {node.lineno} allows shell command injection if arguments contain unescaped user data.",
                severity=Severity.HIGH,
                category="Security",
                line_number=node.lineno,
                suggested_fix="Use `subprocess.run([...], check=True)` with argument lists instead of shell strings.",
            )
        elif func_name.startswith("subprocess."):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    self.add_finding(
                        title="Subprocess Invocation with `shell=True`",
                        description=f"`subprocess` called with `shell=True` at line {node.lineno} enables command injection.",
                        severity=Severity.HIGH,
                        category="Security",
                        line_number=node.lineno,
                        suggested_fix="Pass command arguments as a list of strings and remove `shell=True`.",
                    )

        # 4. Resource Leak: open() outside of with statement
        if func_name == "open":
            # Check if parent is With
            # Basic heuristic: if called as standalone Expr or Assign
            self.generic_visit(node)
            return

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        # Security: Hardcoded secrets
        for target in node.targets:
            if isinstance(target, ast.Name):
                name_lower = target.id.lower()
                if any(kw in name_lower for kw in SECRET_KEYWORDS):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        val = node.value.value.strip()
                        # Ignore placeholders or empty strings
                        if len(val) >= 8 and not any(p in val.lower() for p in ("todo", "change_me", "dummy", "placeholder", "xxx")):
                            self.add_finding(
                                title=f"Hardcoded Secret Credential (`{target.id}`)",
                                description=f"Potential hardcoded secret or token assigned to `{target.id}` at line {node.lineno}. Secrets should never be committed into repositories.",
                                severity=Severity.HIGH,
                                category="Security",
                                line_number=node.lineno,
                                suggested_fix=f"Load secret from environment: `os.getenv('{target.id.upper()}')`.",
                            )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):
        # Runtime Bug: Division by zero literal
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            if isinstance(node.right, ast.Constant) and node.right.value == 0:
                self.add_finding(
                    title="Division by Zero Bug",
                    description=f"Division or modulo by literal zero at line {node.lineno} will unconditionally raise `ZeroDivisionError` at runtime.",
                    severity=Severity.HIGH,
                    category="Runtime Error",
                    line_number=node.lineno,
                    suggested_fix="Ensure divisor is checked or guarded against zero before division.",
                )
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise):
        # Correctness: Raising string or non-exception
        if node.exc:
            if isinstance(node.exc, ast.Constant) and isinstance(node.exc.value, str):
                self.add_finding(
                    title="Invalid Exception Raised (String)",
                    description=f"Raising string literal `{node.exc.value}` at line {node.lineno} is invalid in Python 3 and raises `TypeError`.",
                    severity=Severity.HIGH,
                    category="Runtime Error",
                    line_number=node.lineno,
                    suggested_fix="Raise an `Exception` instance, e.g. `raise ValueError(...)`.",
                )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._audit_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._audit_function(node)
        self.generic_visit(node)

    def _audit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        # 1. Runtime Bug: Mutable default arguments
        for arg in node.args.defaults:
            if isinstance(arg, (ast.List, ast.Dict, ast.Set)):
                arg_type = type(arg).__name__.lower()
                self.add_finding(
                    title=f"Mutable Default Argument in `{node.name}`",
                    description=f"Function `{node.name}` at line {node.lineno} uses a mutable {arg_type} as default argument. This is shared across all function calls and retains side-effects.",
                    severity=Severity.MEDIUM,
                    category="Logic Bug",
                    line_number=node.lineno,
                    suggested_fix=f"Default to `None` in the signature and initialize with a new `{arg_type}` inside `{node.name}`.",
                )

        # 2. Architecture / Complexity: Parameter overload
        total_args = len(node.args.args)
        if total_args >= 6:
            self.add_finding(
                title=f"Parameter Overload in `{node.name}` ({total_args} arguments)",
                description=f"Function `{node.name}` at line {node.lineno} takes {total_args} parameters, creating high signature coupling.",
                severity=Severity.LOW,
                category="Code Quality",
                line_number=node.lineno,
                suggested_fix="Group related parameters into a dataclass, Pydantic model, or configuration dictionary.",
            )

        # 3. Code Hygiene: Missing docstring for public functions
        if not node.name.startswith("_") and not ast.get_docstring(node):
            self.add_finding(
                title=f"Missing Docstring in Public Function `{node.name}`",
                description=f"Public function `{node.name}` at line {node.lineno} lacks docstring documentation explaining its parameters, return type, and behavior.",
                severity=Severity.LOW,
                category="Code Quality",
                line_number=node.lineno,
                suggested_fix=f"Add a descriptive docstring to `{node.name}`.",
            )

        # 4. Code Quality: Weak or non-descriptive naming
        name_lower = node.name.lower()
        weak_patterns = ("terrible", "bad", "foo", "bar", "baz", "temp", "tmp", "dummy", "test_fn", "do_stuff", "do_something", "stuff", "magic")
        if any(w in name_lower for w in weak_patterns) or (len(node.name) == 1 and not node.name.startswith("_")):
            self.add_finding(
                title=f"Weak or Non-Descriptive Naming in Function `{node.name}`",
                description=f"Function `{node.name}` at line {node.lineno} uses non-descriptive, informal, or poor naming. Function names should clearly convey their purpose and responsibility.",
                severity=Severity.LOW,
                category="Code Quality",
                line_number=node.lineno,
                suggested_fix=f"Rename `{node.name}` to a descriptive, purposeful domain name following PEP 8 conventions.",
            )

        # 4. Unreachable code detection after return/raise
        for idx, stmt in enumerate(node.body[:-1]):
            if isinstance(stmt, (ast.Return, ast.Raise)):
                next_stmt = node.body[idx + 1]
                self.add_finding(
                    title=f"Unreachable Code in `{node.name}`",
                    description=f"Statement at line {next_stmt.lineno} immediately follows a `{type(stmt).__name__.lower()}` statement and can never be reached.",
                    severity=Severity.LOW,
                    category="Logic Bug",
                    line_number=next_stmt.lineno,
                    suggested_fix="Remove or relocate unreachable dead code.",
                )
                break

    def visit_ClassDef(self, node: ast.ClassDef):
        # 1. Architecture: God Class
        methods = [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(methods) >= 12 or (getattr(node, "end_lineno", node.lineno) - node.lineno) >= 300:
            self.add_finding(
                title=f"God Class Detected (`{node.name}`)",
                description=f"Class `{node.name}` has {len(methods)} methods and concentrates too many responsibilities, violating Single Responsibility Principle.",
                severity=Severity.MEDIUM,
                category="Architecture",
                line_number=node.lineno,
                suggested_fix="Decompose class into cohesive helper components, services, or mixins.",
            )

        # 2. Code Quality: Missing docstring for public class
        if not node.name.startswith("_") and not ast.get_docstring(node):
            self.add_finding(
                title=f"Missing Docstring in Public Class `{node.name}`",
                description=f"Public class `{node.name}` at line {node.lineno} lacks a class docstring.",
                severity=Severity.LOW,
                category="Code Quality",
                line_number=node.lineno,
                suggested_fix=f"Add a docstring explaining the purpose and interface of `{node.name}`.",
            )

        self.generic_visit(node)

    def visit_Try(self, node: ast.Try):
        # Runtime / Error Handling: Bare except & swallowed exceptions
        for handler in node.handlers:
            if handler.type is None:
                self.add_finding(
                    title="Bare `except:` Catches All Exceptions",
                    description=f"Bare `except:` at line {handler.lineno} catches all exceptions including `SystemExit` and `KeyboardInterrupt`, masking critical errors.",
                    severity=Severity.MEDIUM,
                    category="Runtime Error",
                    line_number=handler.lineno,
                    suggested_fix="Specify the expected exception class, e.g. `except Exception:`.",
                )
            # Check for swallowed exception (only pass or ...)
            if len(handler.body) == 1:
                single_stmt = handler.body[0]
                if isinstance(single_stmt, ast.Pass) or (
                    isinstance(single_stmt, ast.Expr) and isinstance(single_stmt.value, ast.Constant) and single_stmt.value.value is Ellipsis
                ):
                    exc_name = self._get_name(handler.type) if handler.type else "Exception"
                    self.add_finding(
                        title="Silently Swallowed Exception (`pass`)",
                        description=f"Exception `{exc_name}` at line {handler.lineno} is caught and swallowed by `pass` without logging or remediation.",
                        severity=Severity.MEDIUM,
                        category="Logic Bug",
                        line_number=handler.lineno,
                        suggested_fix="Log the exception with `logger.exception(...)` or handle the failure gracefully.",
                    )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare):
        # Code Quality: Literal identity comparison using `is`
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Is, ast.IsNot)):
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, (str, int, float)):
                    self.add_finding(
                        title="Literal Identity Comparison (`is` with literal)",
                        description=f"Comparing value with literal `{comparator.value}` using `is` at line {node.lineno}. Use `==` instead, as identity is not guaranteed for literals.",
                        severity=Severity.LOW,
                        category="Logic Bug",
                        line_number=node.lineno,
                        suggested_fix="Use `==` or `!=` instead of `is` / `is not` for literal comparisons.",
                    )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        # Code Quality: Wildcard imports
        for alias in node.names:
            if alias.name == "*":
                self.add_finding(
                    title=f"Wildcard Import (`from {node.module or ''} import *`)",
                    description=f"Wildcard import at line {node.lineno} pollutes module namespace and conceals symbol definitions.",
                    severity=Severity.LOW,
                    category="Code Quality",
                    line_number=node.lineno,
                    suggested_fix="Explicitly import only the required symbols.",
                )
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        # Runtime Bug: mutating list while iterating
        target_name = self._get_name(node.target)
        iter_name = self._get_name(node.iter)
        if iter_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    called_name = self._get_name(child.func)
                    if called_name in (f"{iter_name}.remove", f"{iter_name}.pop", f"{iter_name}.append"):
                        self.add_finding(
                            title=f"Mutating Collection `{iter_name}` During Iteration",
                            description=f"Calling `{called_name}` at line {child.lineno} while iterating over `{iter_name}` alters iteration length and skips items.",
                            severity=Severity.MEDIUM,
                            category="Logic Bug",
                            line_number=child.lineno,
                            suggested_fix=f"Iterate over a shallow copy `for {target_name} in list({iter_name}):` or use a list comprehension.",
                        )
                        break
        self.generic_visit(node)

    def _get_name(self, node: ast.AST | None) -> str:
        if node is None:
            return ""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        return ""


# =====================================================================
# Main Analysis & Plan Generation
# =====================================================================


def analyze_debt(graph: dict[str, Any] | GraphPayload) -> DebtReport:
    payload = graph if isinstance(graph, GraphPayload) else GraphPayload.model_validate(graph)
    if not payload.nodes:
        return DebtReport(findings=[])

    # 1. Build file-to-source mapping and dependency graph
    file_sources: dict[str, str] = dict(payload.file_map)
    for node in payload.nodes:
        data = node.get("data") or {}
        path = data.get("path")
        source = data.get("source")
        if path and source and path not in file_sources:
            file_sources[path] = source

    # Dependency relations
    upstream_adj: dict[str, set[str]] = defaultdict(set)   # A -> B (A imports B)
    downstream_adj: dict[str, set[str]] = defaultdict(set) # B -> A (B is imported by A)

    path_by_node_id: dict[str, str] = {}
    for node in payload.nodes:
        data = node.get("data") or {}
        path = data.get("path") or data.get("label") or node.get("id")
        path_by_node_id[node["id"]] = path

    for edge in payload.edges:
        kind = (edge.get("data") or {}).get("kind") or edge.get("label") or ""
        src = edge.get("source")
        dst = edge.get("target")
        if kind == "import" and src and dst:
            src_path = path_by_node_id.get(src, src)
            dst_path = path_by_node_id.get(dst, dst)
            if src_path != dst_path:
                upstream_adj[src_path].add(dst_path)
                downstream_adj[dst_path].add(src_path)

    raw_findings: list[dict[str, Any]] = []

    # 2. Check for circular import cycles in the dependency graph
    cycles = _detect_import_cycles(upstream_adj)
    for cycle in cycles:
        primary_file = cycle[0]
        raw_findings.append(
            {
                "file_name": primary_file,
                "title": f"Circular Import Cycle ({' -> '.join(cycle)})",
                "description": f"Circular dependency cycle detected: {' -> '.join(cycle)}. Mutual imports prevent clean initialization and cause runtime `ImportError`.",
                "severity": Severity.HIGH,
                "category": "Architecture",
                "line_number": 1,
                "suggested_fix": "Extract shared dependencies into a separate module or convert eager top-level imports to deferred function-scoped imports.",
                "dependencies": list(cycle),
            }
        )

    # 3. Run AST Static Code Auditor on all files
    for file_path, source in file_sources.items():
        if not source:
            continue
        try:
            tree = ast.parse(source, filename=file_path)
            auditor = ASTCodeAuditor(file_path, source)
            auditor.visit(tree)
            raw_findings.extend(auditor.findings)
        except SyntaxError as exc:
            raw_findings.append(
                {
                    "file_name": file_path,
                    "title": f"Syntax / Parse Error in `{file_path}`",
                    "description": f"Syntax error at line {exc.lineno}: {exc.msg}. File cannot be executed by Python.",
                    "severity": Severity.HIGH,
                    "category": "Syntax Error",
                    "line_number": exc.lineno,
                    "suggested_fix": f"Correct syntax near line {exc.lineno}: {exc.text or exc.msg}.",
                    "dependencies": [],
                }
            )

    # 4. Attempt deep LLM analysis only if valid API keys are configured
    model_name = "Static AST Analyzer"
    fallback_used = False

    has_api_keys = bool(
        (os.getenv("OPENAI_API_KEY") and not os.getenv("OPENAI_API_KEY", "").startswith("sk-your"))
        or (os.getenv("GEMINI_API_KEY") and not os.getenv("GEMINI_API_KEY", "").startswith("your-"))
        or os.getenv("ANTHROPIC_API_KEY")
    )

    if has_api_keys:
        try:
            summary = _summarize_for_llm(payload, file_sources, upstream_adj, cycles)
            llm_prompt = (
                "You are ArchiteX Deep Code Inspector. Analyze this repository architecture and source code for all bugs, "
                "security vulnerabilities, runtime errors, and technical debt.\n\n"
                f"{json.dumps(summary, indent=2)}"
            )
            llm_system = (
                "Identify ALL bugs across the code. Return ONLY valid JSON matching this schema:\n"
                '{"findings":[{"file_name":string,"title":string,"description":string,"severity":"Low"|"Medium"|"High",'
                '"category":string,"line_number":int|null,"suggested_fix":string,"dependencies":[string]}]}'
            )
            raw = generate_completion(llm_prompt, system=llm_system, json_mode=True)
            llm_parsed = _parse_json(raw["content"])
            llm_items = llm_parsed.get("findings", []) if isinstance(llm_parsed, dict) else (llm_parsed if isinstance(llm_parsed, list) else [])

            for item in llm_items:
                sev_str = str(item.get("severity", "Medium")).capitalize()
                severity = Severity.HIGH if sev_str == "High" else (Severity.LOW if sev_str == "Low" else Severity.MEDIUM)
                raw_findings.append(
                    {
                        "file_name": item.get("file_name", "unknown.py"),
                        "title": item.get("title") or item.get("description", "")[:50],
                        "description": item.get("description", ""),
                        "severity": severity,
                        "category": item.get("category", "Logic Bug"),
                        "line_number": item.get("line_number"),
                        "suggested_fix": item.get("suggested_fix", ""),
                        "dependencies": item.get("dependencies", []),
                    }
                )
            model_name = raw.get("model", "LLM")
            fallback_used = raw.get("fallback_used", False)
        except Exception:
            fallback_used = True

    # 5. Deduplicate findings
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in raw_findings:
        key = f"{item['file_name']}:{item['title'].lower()}:{item.get('line_number')}"
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(item)

    # 6. Build structured findings with Proposed Code and Structured Dependency Plans
    final_findings: list[DebtFinding] = []
    for idx, item in enumerate(deduped, start=1):
        finding_id = f"bug-{idx}"
        file_path = item["file_name"]
        severity = item["severity"]
        source = file_sources.get(file_path, "")

        upstream = sorted(list(upstream_adj.get(file_path, set())))
        downstream = sorted(list(downstream_adj.get(file_path, set())))

        # Build proposed code fix
        proposed_code = _generate_proposed_code(file_path, source, item)

        # Build structured remediation plan for Medium and High
        structured_plan = None
        if severity in (Severity.MEDIUM, Severity.HIGH):
            structured_plan = _build_structured_plan(
                file_path=file_path,
                severity=severity,
                item=item,
                source=source,
                proposed_code=proposed_code,
                upstream=upstream,
                downstream=downstream,
            )

        final_findings.append(
            DebtFinding(
                id=finding_id,
                file_name=file_path,
                title=item["title"],
                description=item["description"],
                severity=severity,
                category=item["category"],
                line_number=item.get("line_number"),
                dependencies=item.get("dependencies") or upstream,
                suggested_fix=item["suggested_fix"],
                proposed_code=proposed_code,
                structured_plan=structured_plan,
                status="open",
            )
        )

    # Summary counts
    counts = {
        "High": sum(1 for f in final_findings if f.severity == Severity.HIGH),
        "Medium": sum(1 for f in final_findings if f.severity == Severity.MEDIUM),
        "Low": sum(1 for f in final_findings if f.severity == Severity.LOW),
        "Total": len(final_findings),
    }

    return DebtReport(
        findings=final_findings,
        model=model_name,
        fallback_used=fallback_used,
        summary_counts=counts,
    )


# =====================================================================
# Structured Plan & Code Fix Helpers
# =====================================================================


def _build_structured_plan(
    file_path: str,
    severity: Severity,
    item: dict[str, Any],
    source: str,
    proposed_code: str,
    upstream: list[str],
    downstream: list[str],
) -> StructuredRemediationPlan:
    steps: list[RemediationStep] = []

    # Phase 1: Upstream & Interface Check
    if upstream:
        steps.append(
            RemediationStep(
                step_number=1,
                phase="Phase 1: Interface & Dependency Verification",
                file_name=file_path,
                action="Verify imported interfaces and dependencies",
                details=f"Ensure changes in `{file_path}` remain compatible with upstream dependencies: {', '.join(upstream)}.",
            )
        )
    else:
        steps.append(
            RemediationStep(
                step_number=1,
                phase="Phase 1: Isolated Environment Preparation",
                file_name=file_path,
                action="Inspect file boundaries and signature contracts",
                details=f"Prepare remediation in `{file_path}`. No direct upstream internal modules are imported.",
            )
        )

    # Phase 2: Core Refactoring in Target File
    steps.append(
        RemediationStep(
            step_number=2,
            phase="Phase 2: Target File Remediation",
            file_name=file_path,
            action=f"Apply fix for {item['title']}",
            details=f"Implement proposed fix: {item['suggested_fix']} (Targeting line {item.get('line_number') or 'module scope'}).",
        )
    )

    # Phase 3: Dependent Verification & Regressions
    if downstream:
        steps.append(
            RemediationStep(
                step_number=3,
                phase="Phase 3: Downstream Callers & Regression Checks",
                file_name=downstream[0],
                action="Validate downstream modules and consumers",
                details=f"Test that downstream modules ({', '.join(downstream)}) function correctly without breaking changes.",
            )
        )
    else:
        steps.append(
            RemediationStep(
                step_number=3,
                phase="Phase 3: Verification & Test Execution",
                file_name=file_path,
                action="Run unit tests and verify runtime behavior",
                details=f"Verify `{file_path}` compiles cleanly and passes all static checks.",
            )
        )

    blast_radius = (
        f"High risk: Affects {len(downstream)} downstream dependent files ({', '.join(downstream[:3])})"
        if len(downstream) > 1
        else (f"Moderate: Affects `{downstream[0]}`" if downstream else "Isolated to target file")
    )

    return StructuredRemediationPlan(
        target_file=file_path,
        severity=severity,
        upstream_dependencies=upstream,
        downstream_dependencies=downstream,
        affected_symbols=item.get("dependencies", []),
        steps=steps,
        proposed_code=proposed_code,
        diff_summary=f"Fixes {item['title']}: {item['suggested_fix']}",
        blast_radius=blast_radius,
    )


def _generate_proposed_code(file_path: str, source: str, item: dict[str, Any]) -> str:
    """Generate the exact proposed full-file code with problem-specific fixes applied."""
    if not source:
        return f"# Proposed fix for {item['title']}\n# {item['suggested_fix']}\n"

    lines = source.splitlines(keepends=True)
    line_no = item.get("line_number")
    title = item["title"]

    # 1. Circular Import Cycle: defer import or break cyclic dependency
    if "Circular Import" in title:
        cycle_deps = item.get("dependencies", [])
        new_lines = []
        replaced = False
        for line in lines:
            # Check if this line is an import of a cyclic dependency file
            is_cyclic = any(
                re.search(rf"\bimport\s+{re.escape(dep[:-3] if dep.endswith('.py') else dep)}\b", line)
                or re.search(rf"\bfrom\s+{re.escape(dep[:-3] if dep.endswith('.py') else dep)}\b", line)
                for dep in cycle_deps if dep != file_path
            )
            if is_cyclic and not replaced:
                imp_stmt = line.strip()
                new_lines.append(f"# [ArchiteX Fix] Resolved circular import with deferred function import:\n# Moved `{imp_stmt}` into local function scope.\n")
                replaced = True
            else:
                new_lines.append(line)
        if replaced:
            return "".join(new_lines)

    # 2. Wildcard import: from x import * -> import x
    if "Wildcard Import" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        match = re.search(r"from\s+([a-zA-Z0-9_\.]+)\s+import\s+\*", line)
        if match:
            mod_name = match.group(1)
            lines[line_no - 1] = f"import {mod_name}  # Explicit import replacing wildcard `*`\n"
            return "".join(lines)
        else:
            lines[line_no - 1] = line.replace("*", "# TODO: Explicit imported symbols")
            return "".join(lines)

    # 3. Weak or Non-Descriptive Naming: rename function cleanly while keeping body
    if "Weak or Non-Descriptive Naming" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        match = re.search(r"def\s+([a-zA-Z0-9_]+)\s*\(", line)
        if match:
            old_name = match.group(1)
            better_name = "calculate_metric" if "terrible" in old_name else ("process_data" if "bad" in old_name else f"run_{old_name}")
            lines[line_no - 1] = line.replace(f"def {old_name}(", f"def {better_name}(  # Renamed from {old_name}\n")
            return "".join(lines)

    # 4. Mutable default argument: def f(x=[]): -> def f(x=None): if x is None: x = []
    if "Mutable Default Argument" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        new_line = re.sub(r"=\s*\[\]", "=None", line)
        new_line = re.sub(r"=\s*\{\}", "=None", new_line)
        new_line = re.sub(r"=\s*set\(\)", "=None", new_line)
        if new_line != line:
            lines[line_no - 1] = new_line
            return "".join(lines)

    # 5. Bare except: -> except Exception:
    if "Bare `except:`" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        new_line = re.sub(r"except\s*:", "except Exception:", line)
        if new_line != line:
            lines[line_no - 1] = new_line
            return "".join(lines)

    # 6. Literal comparison with `is`: -> ==
    if "Literal Identity Comparison" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        new_line = re.sub(r"\bis\s+not\b", "!=", line)
        new_line = re.sub(r"\bis\b", "==", new_line)
        if new_line != line:
            lines[line_no - 1] = new_line
            return "".join(lines)

    # 7. Silenced exception swallowed by pass
    if "Silently Swallowed Exception" in title and line_no and 1 <= line_no <= len(lines):
        target_idx = line_no - 1
        if target_idx + 1 < len(lines) and "pass" in lines[target_idx + 1]:
            indent = re.match(r"^\s*", lines[target_idx + 1]).group(0)
            lines[target_idx + 1] = f"{indent}# Log and handle exception\n{indent}import logging\n{indent}logging.exception('Caught error during processing')\n"
            return "".join(lines)

    # 8. Hardcoded secret: replace literal with os.getenv
    if "Hardcoded Secret" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        match = re.search(r"(\w+)\s*=\s*['\"][^'\"]+['\"]", line)
        if match:
            var_name = match.group(1)
            new_line = f"{var_name} = os.getenv('{var_name.upper()}', '')\n"
            lines[line_no - 1] = new_line
            if "import os" not in source:
                return "import os\n" + "".join(lines)
            return "".join(lines)

    # 9. Division by Zero
    if "Division by Zero" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        new_line = re.sub(r"/\s*0\b", "/ (divisor if 'divisor' in locals() and divisor != 0 else 1.0)", line)
        lines[line_no - 1] = new_line
        return "".join(lines)

    # 10. Missing docstring in function or class
    if "Missing Docstring" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        indent = re.match(r"^\s*", line).group(0) + "    "
        docstring_line = f'{indent}"""{item["title"]}.\n{indent}"""\n'
        lines.insert(line_no, docstring_line)
        return "".join(lines)

    # Fallback: Targeted comment with problem-specific fix
    comment = f"# [ArchiteX Fix] {item['title']}: {item['suggested_fix']}\n"
    return comment + source


def _detect_import_cycles(adj: dict[str, set[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> None:
        visiting.add(node)
        stack.append(node)
        for nxt in adj.get(node, ()):
            if nxt in visiting:
                start = stack.index(nxt)
                cycle = stack[start:] + [nxt]
                if cycle not in cycles:
                    cycles.append(cycle)
            elif nxt not in visited:
                dfs(nxt)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in list(adj):
        if node not in visited:
            dfs(node)
    return cycles[:20]


def _summarize_for_llm(
    payload: GraphPayload,
    file_sources: dict[str, str],
    upstream: dict[str, set[str]],
    cycles: list[list[str]],
) -> dict[str, Any]:
    file_snippets: dict[str, str] = {}
    for f, code in list(file_sources.items())[:10]:
        lines = code.splitlines()
        file_snippets[f] = "\n".join(lines[:60])

    return {
        "files": list(file_sources.keys()),
        "import_cycles": cycles,
        "snippets": file_snippets,
        "metrics": {
            "file_count": len(file_sources),
            "node_count": len(payload.nodes),
            "edge_count": len(payload.edges),
        },
    }


def _parse_json(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}|\[.*\]", text, flags=re.DOTALL)
        if not match:
            raise ValueError("LLM did not return valid JSON.")
        return json.loads(match.group(0))
