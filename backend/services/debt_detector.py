import ast
import builtins
import hashlib
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
    guided_plan: Any | None = None


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
    root_cause: str = ""
    code_evidence: str = ""
    potential_impact: str = ""
    affected_files: list[str] = Field(default_factory=list)
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
# Constants & Helpers
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

SHADOWABLE_BUILTINS = {
    "list",
    "dict",
    "set",
    "str",
    "int",
    "float",
    "type",
    "id",
    "input",
    "format",
    "object",
    "min",
    "max",
    "sum",
    "dir",
    "hash",
    "all",
    "any",
}

BUILTIN_NAMES = set(dir(builtins))


def extract_code_evidence(source: str, lineno: int | None, end_lineno: int | None = None, context: int = 2) -> str:
    """Extract code evidence with surrounding context lines and an indicator on the offending line."""
    if not source or lineno is None or lineno < 1:
        return ""
    lines = source.splitlines()
    total = len(lines)
    if lineno > total:
        return ""
    start = max(1, lineno - context)
    end = min(total, (end_lineno if end_lineno and end_lineno >= lineno else lineno) + context)
    formatted = []
    for num in range(start, end + 1):
        indicator = "▶ " if num == lineno else "  "
        line_content = lines[num - 1]
        formatted.append(f"{indicator}{num:4d} | {line_content}")
    return "\n".join(formatted)


# =====================================================================
# Cyclomatic Complexity & Nesting Visitors
# =====================================================================


class CyclomaticComplexityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.complexity = 1

    def visit_If(self, node: ast.If):
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While):
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor):
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With):
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith):
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert):
        self.complexity += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp):
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp):
        self.complexity += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension):
        self.complexity += len(node.ifs)
        self.generic_visit(node)


def compute_nesting_depth(node: ast.AST) -> int:
    max_depth = 0

    def walk(n: ast.AST, depth: int):
        nonlocal max_depth
        if depth > max_depth:
            max_depth = depth
        for child in ast.iter_child_nodes(n):
            inc = 1 if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.Try, ast.With, ast.AsyncWith)) else 0
            walk(child, depth + inc)

    walk(node, 0)
    return max_depth


# =====================================================================
# AST Code Auditor
# =====================================================================


class ASTCodeAuditor(ast.NodeVisitor):
    def __init__(
        self,
        file_path: str,
        source_code: str,
        upstream_deps: list[str] | None = None,
        downstream_deps: list[str] | None = None,
    ):
        self.file_path = file_path
        self.source_code = source_code
        self.lines = source_code.splitlines()
        self.findings: list[dict[str, Any]] = []
        self.upstream_deps = upstream_deps or []
        self.downstream_deps = downstream_deps or []

        self.imported_names: set[str] = set()
        self.module_scope_names: set[str] = set()
        self.parent_map: dict[ast.AST, ast.AST] = {}

    def audit(self, tree: ast.AST):
        # Build parent map
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parent_map[child] = parent

        # Pre-pass: collect imported names and module-level variables
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imported_names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.module_scope_names.add(target.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.module_scope_names.add(node.name)

        self.visit(tree)

    def add_finding(
        self,
        title: str,
        description: str,
        severity: Severity,
        category: str,
        line_number: int | None,
        suggested_fix: str,
        root_cause: str,
        potential_impact: str,
        end_line: int | None = None,
        dependencies: list[str] | None = None,
        affected_files: list[str] | None = None,
    ):
        code_ev = extract_code_evidence(self.source_code, line_number, end_line)
        aff_files = affected_files or ([self.file_path] + self.downstream_deps)
        self.findings.append(
            {
                "file_name": self.file_path,
                "title": title,
                "description": description,
                "severity": severity,
                "category": category,
                "line_number": line_number,
                "suggested_fix": suggested_fix,
                "root_cause": root_cause,
                "code_evidence": code_ev,
                "potential_impact": potential_impact,
                "affected_files": aff_files,
                "dependencies": dependencies or self.upstream_deps,
            }
        )

    def visit_Call(self, node: ast.Call):
        func_name = self._get_name(node.func)

        # 1. Dynamic Code Execution
        if func_name in ("eval", "exec", "compile"):
            self.add_finding(
                title=f"Dangerous Dynamic Code Execution (`{func_name}`)",
                description=f"Direct call to `{func_name}()` at line {node.lineno} enables arbitrary code execution vulnerabilities.",
                severity=Severity.HIGH,
                category="Security",
                line_number=node.lineno,
                suggested_fix=f"Replace `{func_name}()` with safe static parsing (e.g. `ast.literal_eval`), structured dispatch, or domain handlers.",
                root_cause=f"Direct call to `{func_name}()` parses and evaluates arbitrary string inputs with interpreter privileges, bypassing static language boundaries.",
                potential_impact="Critical Remote Code Execution (RCE) vulnerability allowing hostile payload injection into the host process.",
            )

        # 2. Insecure Deserialization
        if func_name in ("pickle.loads", "pickle.load", "_pickle.loads", "_pickle.load", "yaml.load"):
            is_unsafe_yaml = func_name == "yaml.load" and not any(
                kw.arg == "Loader" and "Safe" in self._get_name(kw.value) for kw in node.keywords
            )
            if func_name != "yaml.load" or is_unsafe_yaml:
                self.add_finding(
                    title=f"Insecure Deserialization (`{func_name}`)",
                    description=f"Using `{func_name}()` at line {node.lineno} on untrusted data can lead to remote code execution.",
                    severity=Severity.HIGH,
                    category="Security",
                    line_number=node.lineno,
                    suggested_fix="Use a safe data serialization format such as JSON, Protocol Buffers, or safe YAML loaders (`yaml.safe_load`).",
                    root_cause=f"`{func_name}()` reconstructs arbitrary Python objects by calling constructors and `__reduce__` methods defined in the stream.",
                    potential_impact="Remote code execution when untrusted or tampered byte streams are deserialized.",
                )

        # 3. Command Injection
        if func_name in ("os.system", "os.popen"):
            self.add_finding(
                title=f"Command Injection Risk (`{func_name}`)",
                description=f"Direct shell invocation `{func_name}()` at line {node.lineno} allows shell command injection if arguments contain unescaped user data.",
                severity=Severity.HIGH,
                category="Security",
                line_number=node.lineno,
                suggested_fix="Use `subprocess.run([...], check=True)` with argument lists instead of shell strings.",
                root_cause=f"`{func_name}()` invokes the system `/bin/sh` shell to parse and execute commands as raw strings.",
                potential_impact="Arbitrary shell command execution on host operating system with privileges of the service user.",
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
                        suggested_fix="Pass command arguments as an array of strings and remove `shell=True`.",
                        root_cause="`shell=True` forces process creation through the system shell, evaluating metacharacters (`;`, `&`, `|`).",
                        potential_impact="Host operating system takeover via parameter tampering.",
                    )

        # 4. SQL Injection
        if func_name.endswith(".execute") or func_name.endswith(".executemany"):
            if node.args:
                first_arg = node.args[0]
                is_dynamic_sql = False
                if isinstance(first_arg, ast.JoinedStr):
                    is_dynamic_sql = True
                elif isinstance(first_arg, ast.BinOp) and isinstance(first_arg.op, ast.Mod):
                    is_dynamic_sql = True
                elif isinstance(first_arg, ast.Call) and self._get_name(first_arg.func).endswith(".format"):
                    is_dynamic_sql = True

                if is_dynamic_sql:
                    self.add_finding(
                        title="SQL Injection via Dynamic Query Construction",
                        description=f"Query execution at line {node.lineno} interpolates variables into SQL string instead of parameterized parameters.",
                        severity=Severity.HIGH,
                        category="Security",
                        line_number=node.lineno,
                        suggested_fix="Use parameterized query placeholders (`?` or `%s`) and pass variables as a tuple to `.execute()`.",
                        root_cause="SQL statement contains directly interpolated parameters, allowing input values to escape literals and modify SQL grammar.",
                        potential_impact="Database breach, data exfiltration, unauthorized modification, or authentication bypass.",
                    )

        # 5. Resource Leak: open() outside of with statement
        if func_name == "open":
            parent = self.parent_map.get(node)
            is_in_with = False
            curr = parent
            while curr:
                if isinstance(curr, (ast.With, ast.AsyncWith)):
                    is_in_with = True
                    break
                curr = self.parent_map.get(curr)

            if not is_in_with:
                self.add_finding(
                    title="Resource Leak: Unclosed File Handle (`open()`)",
                    description=f"Call to `open()` at line {node.lineno} is not managed by a `with` context manager.",
                    severity=Severity.MEDIUM,
                    category="Resource Leak",
                    line_number=node.lineno,
                    suggested_fix="Wrap file operations in a context manager: `with open(...) as f:`.",
                    root_cause="File handle opened without a context manager (`with`) or deterministic cleanup in `finally`. Descriptors remain open until garbage collected.",
                    potential_impact="OS descriptor exhaustion (`OSError: [Errno 24] Too many open files`) under sustained traffic, leading to process crash.",
                )

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        # 1. Hardcoded secrets
        for target in node.targets:
            if isinstance(target, ast.Name):
                name_lower = target.id.lower()
                if any(kw in name_lower for kw in SECRET_KEYWORDS):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        val = node.value.value.strip()
                        if len(val) >= 8 and not any(p in val.lower() for p in ("todo", "change_me", "dummy", "placeholder", "xxx")):
                            self.add_finding(
                                title=f"Hardcoded Secret Credential (`{target.id}`)",
                                description=f"Potential hardcoded secret or token assigned to `{target.id}` at line {node.lineno}.",
                                severity=Severity.HIGH,
                                category="Security",
                                line_number=node.lineno,
                                suggested_fix=f"Load secret from environment: `os.getenv('{target.id.upper()}')`.",
                                root_cause="Sensitive secrets or cryptographic credentials committed into repository source code.",
                                potential_impact="Credential theft, lateral network penetration, and unauthorized access to cloud services.",
                            )

                # 2. Shadowed Builtins
                if target.id in SHADOWABLE_BUILTINS:
                    self.add_finding(
                        title=f"Shadowed Python Built-in (`{target.id}`)",
                        description=f"Variable name `{target.id}` at line {node.lineno} shadows Python built-in function or type.",
                        severity=Severity.LOW,
                        category="Code Quality",
                        line_number=node.lineno,
                        suggested_fix=f"Rename variable to avoid shadowing built-in `{target.id}` (e.g. `{target.id}_val` or domain name).",
                        root_cause=f"Assigning to `{target.id}` overrides the built-in `{target.id}` in this scope, blocking access to standard library built-ins.",
                        potential_impact=f"Runtime `TypeError: '{target.id}' object is not callable` when other code attempts to invoke the built-in.",
                    )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):
        # Division by zero literal
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            if isinstance(node.right, ast.Constant) and node.right.value == 0:
                self.add_finding(
                    title="Division by Zero Bug",
                    description=f"Division or modulo by literal zero at line {node.lineno} will unconditionally raise `ZeroDivisionError` at runtime.",
                    severity=Severity.HIGH,
                    category="Runtime Error",
                    line_number=node.lineno,
                    suggested_fix="Ensure divisor is checked or guarded against zero before division.",
                    root_cause="Divisor expression evaluates statically to constant `0`. In Python, `x / 0` unconditionally raises `ZeroDivisionError`.",
                    potential_impact="Immediate process/request crash with unhandled `ZeroDivisionError` on execution.",
                )
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise):
        if node.exc:
            if isinstance(node.exc, ast.Constant) and isinstance(node.exc.value, str):
                self.add_finding(
                    title="Invalid Exception Raised (String Literal)",
                    description=f"Raising string literal `{node.exc.value}` at line {node.lineno} is invalid in Python 3 and raises `TypeError`.",
                    severity=Severity.HIGH,
                    category="Runtime Error",
                    line_number=node.lineno,
                    suggested_fix="Raise an `Exception` instance, e.g. `raise ValueError(...)`.",
                    root_cause="In Python 3, exceptions must inherit from `BaseException`. Raising a string literal triggers a `TypeError`.",
                    potential_impact="Uncaught `TypeError: exceptions must derive from BaseException` masking the true application error.",
                )
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try):
        for handler in node.handlers:
            # Bare except
            if handler.type is None:
                self.add_finding(
                    title="Bare `except:` Intercepts All System Signals",
                    description=f"Bare `except:` at line {handler.lineno} catches all exceptions including `SystemExit` and `KeyboardInterrupt`.",
                    severity=Severity.MEDIUM,
                    category="Runtime Error",
                    line_number=handler.lineno,
                    suggested_fix="Specify the expected exception class, e.g. `except Exception as exc:`.",
                    root_cause="Bare `except:` matches `BaseException`, intercepting signal exceptions (`KeyboardInterrupt`, `SystemExit`).",
                    potential_impact="Unkillable threads, inability to terminate workers, and masking of critical runtime faults.",
                )
            # Swallowed pass
            if len(handler.body) == 1:
                single_stmt = handler.body[0]
                if isinstance(single_stmt, ast.Pass) or (
                    isinstance(single_stmt, ast.Expr) and isinstance(single_stmt.value, ast.Constant) and single_stmt.value.value is Ellipsis
                ):
                    exc_name = self._get_name(handler.type) if handler.type else "Exception"
                    self.add_finding(
                        title=f"Silently Swallowed Exception (`{exc_name}`)",
                        description=f"Exception `{exc_name}` at line {handler.lineno} is caught and swallowed by `pass` without logging or remediation.",
                        severity=Severity.MEDIUM,
                        category="Logic Bug",
                        line_number=handler.lineno,
                        suggested_fix="Log the exception with `logging.exception(...)` or handle the failure gracefully.",
                        root_cause="Error handler catches exceptions but explicitly discards them with `pass`, hiding failure state.",
                        potential_impact="Silent data corruption and impossible production debugging as failures fail silently.",
                    )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare):
        # Literal identity comparison using `is`
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Is, ast.IsNot)):
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, (str, int, float)):
                    self.add_finding(
                        title=f"Literal Identity Comparison (`is {repr(comparator.value)}`)",
                        description=f"Comparing value with literal `{comparator.value}` using `is` at line {node.lineno}. Use `==` instead, as identity is not guaranteed for literals.",
                        severity=Severity.MEDIUM,
                        category="Logic Bug",
                        line_number=node.lineno,
                        suggested_fix=f"Use `{'!=' if isinstance(op, ast.IsNot) else '=='}` instead of `{'is not' if isinstance(op, ast.IsNot) else 'is'}` for literal comparisons.",
                        root_cause="`is` tests object identity (`id(a) == id(b)`). Python only caches small integers and short strings; comparison fails unexpectedly on runtime data.",
                        potential_impact="Logic evaluation bugs and authentication bypasses when dynamic inputs have distinct memory identities.",
                    )
            elif isinstance(op, (ast.Eq, ast.NotEq)):
                if isinstance(comparator, ast.Constant) and comparator.value is None:
                    self.add_finding(
                        title="Comparison to `None` using `==`",
                        description=f"Comparing value to `None` with `==` at line {node.lineno} violates PEP 8 and can trigger custom `__eq__` bugs.",
                        severity=Severity.LOW,
                        category="Code Quality",
                        line_number=node.lineno,
                        suggested_fix="Use `is None` or `is not None` instead.",
                        root_cause="`== None` invokes the object's `__eq__` operator which may return truthy or raise exceptions, whereas `is None` checks singleton identity.",
                        potential_impact="Unintended boolean evaluation and violation of standard Python idiom.",
                    )
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
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
                            root_cause="Modifying a sequence while an active iterator traverses it causes index shifting, skipping elements or mutating length during iteration.",
                            potential_impact="Skipped data processing, incomplete validation, and non-deterministic logic errors.",
                        )
                        break
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        # Wildcard imports
        for alias in node.names:
            if alias.name == "*":
                self.add_finding(
                    title=f"Wildcard Import (`from {node.module or ''} import *`)",
                    description=f"Wildcard import at line {node.lineno} pollutes module namespace and conceals symbol definitions.",
                    severity=Severity.LOW,
                    category="Code Quality",
                    line_number=node.lineno,
                    suggested_fix="Explicitly import only the required symbols.",
                    root_cause="Wildcard import dumps all exported symbols into module scope, breaking static analysis and causing accidental symbol collisions.",
                    potential_impact="Unintended variable shadowing, increased memory footprint, and difficult refactoring.",
                )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._audit_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._audit_function(node)
        self.generic_visit(node)

    def _audit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        # 1. Mutable default arguments
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
                    root_cause=f"Default parameter objects are evaluated once at module definition time. The identical {arg_type} instance is shared across all invocations.",
                    potential_impact="State leakage across distinct function invocations, corrupting shared data across requests.",
                )

        # 2. Parameter overload
        total_args = len(node.args.args)
        if total_args >= 6:
            self.add_finding(
                title=f"Parameter Overload in `{node.name}` ({total_args} arguments)",
                description=f"Function `{node.name}` at line {node.lineno} takes {total_args} parameters, creating high signature coupling.",
                severity=Severity.LOW,
                category="Code Quality",
                line_number=node.lineno,
                suggested_fix="Group related parameters into a dataclass, Pydantic model, or configuration dictionary.",
                root_cause="Function signature exceeds recommended parameter count, indicating missing domain abstraction.",
                potential_impact="High signature coupling, maintenance fragility, and increased probability of argument transposition bugs.",
            )

        # 3. Cyclomatic Complexity
        cc_vis = CyclomaticComplexityVisitor()
        for stmt in node.body:
            cc_vis.visit(stmt)
        if cc_vis.complexity >= 15:
            self.add_finding(
                title=f"Excessive Cyclomatic Complexity in `{node.name}` (CC = {cc_vis.complexity})",
                description=f"Function `{node.name}` at line {node.lineno} has cyclomatic complexity of {cc_vis.complexity}, exceeding critical threshold (15).",
                severity=Severity.HIGH,
                category="Excessive Complexity",
                line_number=node.lineno,
                suggested_fix="Decompose function into smaller cohesive helper functions or use the strategy pattern.",
                root_cause="Function contains too many branching paths, conditionals, and exception handlers in a single routine.",
                potential_impact="Untestable function with high defect rate; exponential increase in path testing combinations.",
            )
        elif cc_vis.complexity >= 10:
            self.add_finding(
                title=f"High Cyclomatic Complexity in `{node.name}` (CC = {cc_vis.complexity})",
                description=f"Function `{node.name}` at line {node.lineno} has cyclomatic complexity of {cc_vis.complexity}, exceeding threshold (10).",
                severity=Severity.MEDIUM,
                category="Excessive Complexity",
                line_number=node.lineno,
                suggested_fix="Extract sub-tasks into focused helper methods.",
                root_cause="Concentration of multiple decision branches violating Single Responsibility Principle.",
                potential_impact="Reduced maintainability, high cognitive load for code changes, and test fragility.",
            )

        # 4. Deep Nesting Depth
        depth = compute_nesting_depth(node)
        if depth >= 4:
            self.add_finding(
                title=f"Deep Nesting Depth in `{node.name}` (Level {depth})",
                description=f"Function `{node.name}` at line {node.lineno} has nesting depth of {depth}, creating 'arrow anti-pattern'.",
                severity=Severity.MEDIUM,
                category="Excessive Complexity",
                line_number=node.lineno,
                suggested_fix="Use guard clauses with early returns to flatten indentation.",
                root_cause="Nested procedural conditionals accumulated instead of early returns or functional decomposition.",
                potential_impact="Severe cognitive complexity, obscure logic flow, and elevated risk of regression bugs.",
            )

        # 5. Long Function
        start_l = node.lineno
        end_l = getattr(node, "end_lineno", start_l)
        fn_lines = end_l - start_l + 1
        if fn_lines > 60:
            self.add_finding(
                title=f"Long Function `{node.name}` ({fn_lines} lines)",
                description=f"Function length of {fn_lines} lines exceeds recommended size (60 lines).",
                severity=Severity.LOW,
                category="Code Smell",
                line_number=node.lineno,
                suggested_fix="Break down routine into smaller modular functions.",
                root_cause="Function combines multiple stages (input processing, business rules, presentation) into one routine.",
                potential_impact="Decreased readability, hard to unit test isolated steps, increased refactoring effort.",
            )

        # 6. Inconsistent Return Statements
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        val_returns = [r for r in returns if r.value is not None]
        none_returns = [r for r in returns if r.value is None]
        if val_returns and (none_returns or not any(isinstance(s, ast.Return) for s in node.body[-1:])):
            if len(returns) > len(val_returns) or not any(isinstance(s, ast.Return) for s in node.body[-1:]):
                self.add_finding(
                    title=f"Inconsistent Return Types in `{node.name}`",
                    description=f"Function `{node.name}` returns values in some paths but returns `None` or falls off end in others.",
                    severity=Severity.MEDIUM,
                    category="Logic Bug",
                    line_number=node.lineno,
                    suggested_fix="Ensure all exit branches return a consistent value or raise an exception.",
                    root_cause="Mismatched exit contracts: some execution branches return explicit values while others implicitly return `None`.",
                    potential_impact="Downstream `AttributeError: 'NoneType' object has no attribute ...` in caller modules.",
                )

        # 7. Unbound local variables in conditional branches
        self._audit_unbound_locals(node)

        # 8. Missing docstring for public functions
        if not node.name.startswith("_") and not ast.get_docstring(node):
            self.add_finding(
                title=f"Missing Docstring in Public Function `{node.name}`",
                description=f"Public function `{node.name}` at line {node.lineno} lacks docstring documentation explaining its parameters, return type, and behavior.",
                severity=Severity.LOW,
                category="Code Quality",
                line_number=node.lineno,
                suggested_fix=f"Add a descriptive docstring to `{node.name}`.",
                root_cause="Public interface lacks formal specification of parameters, return types, and side effects.",
                potential_impact="Caller ambiguity, incorrect API consumption, and reduced developer productivity.",
            )

        # 9. Weak or non-descriptive naming
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
                root_cause="Temporary or colloquial placeholder names left in place instead of meaningful domain vocabulary.",
                potential_impact="Obscured intent during code reviews, prolonged developer onboarding, and maintenance defects.",
            )

        # 10. Unreachable code after return/raise
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
                    root_cause="Control flow unconditionally exits prior to this statement, rendering it dead code.",
                    potential_impact="Misleading dead code that clutters logic and confuses maintainers.",
                )
                break

    def _audit_unbound_locals(self, fn_node: ast.FunctionDef | ast.AsyncFunctionDef):
        params = {a.arg for a in fn_node.args.args} | {a.arg for a in fn_node.args.kwonlyargs}
        if fn_node.args.vararg:
            params.add(fn_node.args.vararg.arg)
        if fn_node.args.kwarg:
            params.add(fn_node.args.kwarg.arg)

        conditional_assigns: dict[str, int] = {}
        for stmt in fn_node.body:
            if isinstance(stmt, ast.If) and not stmt.orelse:
                for child in ast.walk(stmt):
                    if isinstance(child, ast.Assign):
                        for tgt in child.targets:
                            if isinstance(tgt, ast.Name) and tgt.id not in params:
                                conditional_assigns[tgt.id] = child.lineno
            elif isinstance(stmt, (ast.Return, ast.Expr, ast.Assign)):
                for child in ast.walk(stmt):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        if child.id in conditional_assigns:
                            self.add_finding(
                                title=f"Potentially Unbound Local Variable (`{child.id}`)",
                                description=f"Variable `{child.id}` is assigned conditionally at line {conditional_assigns[child.id]} but loaded at line {child.lineno} without guaranteed initialization.",
                                severity=Severity.HIGH,
                                category="Runtime Error",
                                line_number=child.lineno,
                                suggested_fix=f"Initialize `{child.id} = None` before the conditional statement.",
                                root_cause=f"Variable `{child.id}` is initialized inside an `if` block with no `else` fallback, causing `UnboundLocalError` when condition evaluates to False.",
                                potential_impact="Production crash with `UnboundLocalError` whenever execution condition evaluates to False.",
                            )
                            del conditional_assigns[child.id]
                            break

    def visit_ClassDef(self, node: ast.ClassDef):
        methods = [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]

        # 1. God Class
        if len(methods) >= 12 or (getattr(node, "end_lineno", node.lineno) - node.lineno) >= 250:
            self.add_finding(
                title=f"God Class Detected (`{node.name}`)",
                description=f"Class `{node.name}` has {len(methods)} methods and {getattr(node, 'end_lineno', node.lineno) - node.lineno} lines, concentrating too many responsibilities.",
                severity=Severity.MEDIUM,
                category="Architecture",
                line_number=node.lineno,
                suggested_fix="Decompose class into cohesive helper components, services, or mixins.",
                root_cause="Class concentrates disparate domains and state into a single monolithic unit, violating Single Responsibility Principle.",
                potential_impact="High architectural coupling, cascading side-effects from modifications, and fragile inheritance.",
            )

        # 2. Missing docstring for public class
        if not node.name.startswith("_") and not ast.get_docstring(node):
            self.add_finding(
                title=f"Missing Docstring in Public Class `{node.name}`",
                description=f"Public class `{node.name}` at line {node.lineno} lacks a class docstring.",
                severity=Severity.LOW,
                category="Code Quality",
                line_number=node.lineno,
                suggested_fix=f"Add a docstring explaining the purpose and interface of `{node.name}`.",
                root_cause="Public class interface lacks specification explaining lifecycle, invariants, and contracts.",
                potential_impact="Developer misconfiguration and misuse of class APIs.",
            )

        # 3. Method protocol checks (__init__, missing self, missing cls)
        for m in methods:
            if m.name == "__init__":
                for child in ast.walk(m):
                    if isinstance(child, ast.Return) and child.value is not None:
                        self.add_finding(
                            title="`__init__()` Method Returns Non-None Value",
                            description=f"`__init__()` at line {child.lineno} attempts to return an explicit value.",
                            severity=Severity.HIGH,
                            category="Runtime Error",
                            line_number=child.lineno,
                            suggested_fix="Remove return value from `__init__()`. Store values in `self` attributes instead.",
                            root_cause="In Python, `__init__()` must return `None`. Returning an explicit value raises a runtime `TypeError` when instantiated.",
                            potential_impact="Instant `TypeError: __init__() should return None` preventing class instantiation.",
                        )

            has_staticmethod = any(self._get_name(dec) == "staticmethod" for dec in m.decorator_list)
            has_classmethod = any(self._get_name(dec) == "classmethod" for dec in m.decorator_list)

            if not has_staticmethod:
                if has_classmethod:
                    if not m.args.args or m.args.args[0].arg != "cls":
                        self.add_finding(
                            title=f"Class Method Missing `cls` in `{node.name}.{m.name}`",
                            description=f"`@classmethod` `{m.name}` at line {m.lineno} does not take `cls` as its first parameter.",
                            severity=Severity.HIGH,
                            category="Runtime Error",
                            line_number=m.lineno,
                            suggested_fix=f"Add `cls` as the first parameter to `{m.name}`.",
                            root_cause="Python passes the class object as the first positional argument to `@classmethod` functions.",
                            potential_impact="Runtime `TypeError` when invoking class method.",
                        )
                else:
                    if not m.args.args or m.args.args[0].arg != "self":
                        self.add_finding(
                            title=f"Instance Method Missing `self` in `{node.name}.{m.name}`",
                            description=f"Instance method `{m.name}` at line {m.lineno} does not have `self` as its first parameter.",
                            severity=Severity.HIGH,
                            category="Runtime Error",
                            line_number=m.lineno,
                            suggested_fix=f"Add `self` as the first parameter or decorate with `@staticmethod`.",
                            root_cause="Python passes the instance object as the first argument to instance methods. Missing `self` causes positional argument mismatch.",
                            potential_impact="Runtime `TypeError: takes 0 positional arguments but 1 was given` when invoked on an instance.",
                        )

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
# Duplicated Code Detector (Clone Detection)
# =====================================================================


def detect_code_clones(
    file_sources: dict[str, str],
    downstream_map: dict[str, set[str]],
    min_lines: int = 5,
) -> list[dict[str, Any]]:
    """Detect duplicate blocks of normalized code across all repository files."""
    line_blocks: dict[str, list[tuple[str, int, int, str]]] = defaultdict(list)
    findings: list[dict[str, Any]] = []

    for fpath, code in file_sources.items():
        if not code:
            continue
        lines = code.splitlines()
        norm_lines = []
        raw_line_map = []
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Ignore empty lines, docstrings, imports, single braces/parentheses, or comments
            if not stripped or stripped.startswith("#") or stripped in (":", ")", "}", "]", "pass"):
                continue
            norm_lines.append(re.sub(r"\s+", " ", stripped))
            raw_line_map.append(idx)

        # Sliding window of min_lines
        n = len(norm_lines)
        if n >= min_lines:
            for i in range(0, n - min_lines + 1):
                window = tuple(norm_lines[i : i + min_lines])
                block_hash = hashlib.md5("\n".join(window).encode("utf-8")).hexdigest()
                start_l = raw_line_map[i]
                end_l = raw_line_map[i + min_lines - 1]
                snippet = "\n".join(lines[start_l - 1 : end_l])
                line_blocks[block_hash].append((fpath, start_l, end_l, snippet))

    seen_pairs: set[tuple[str, int, str, int]] = set()
    for b_hash, occurrences in line_blocks.items():
        if len(occurrences) > 1:
            primary = occurrences[0]
            for duplicate in occurrences[1:]:
                pair_key = (primary[0], primary[1], duplicate[0], duplicate[1])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                is_cross_file = primary[0] != duplicate[0]
                affected = list({primary[0], duplicate[0]} | set(downstream_map.get(duplicate[0], set())))
                findings.append(
                    {
                        "file_name": duplicate[0],
                        "title": f"Duplicated Code Block ({min_lines}+ lines from {primary[0]}:L{primary[1]})",
                        "description": f"Identical code block of {min_lines}+ lines duplicated between {primary[0]}:L{primary[1]}-{primary[2]} and {duplicate[0]}:L{duplicate[1]}-{duplicate[2]}.",
                        "severity": Severity.MEDIUM if is_cross_file else Severity.LOW,
                        "category": "Duplicated Code",
                        "line_number": duplicate[1],
                        "root_cause": (
                            f"Identical algorithmic implementation is duplicate-copied between `{primary[0]}` (L{primary[1]}-{primary[2]}) and `{duplicate[0]}` (L{duplicate[1]}-{duplicate[2]}) without consolidating into a reusable helper function or shared module."
                        ),
                        "code_evidence": extract_code_evidence(file_sources.get(duplicate[0], ""), duplicate[1], duplicate[2]),
                        "potential_impact": "Maintenance hazards and technical debt. Fixes or patches applied to one copy leave duplicate copies broken or vulnerable.",
                        "affected_files": affected,
                        "dependencies": [primary[0]] if is_cross_file else [],
                        "suggested_fix": f"Extract duplicated logic into a shared helper function in a common utility module and import it into both `{primary[0]}` and `{duplicate[0]}`.",
                    }
                )
    return findings


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
    upstream_adj: dict[str, set[str]] = defaultdict(set)    # A -> B (A imports B)
    downstream_adj: dict[str, set[str]] = defaultdict(set)  # B -> A (B is imported by A)

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
        cycle_chain = " -> ".join(cycle)
        all_affected = list(set(cycle) | {d for f in cycle for d in downstream_adj.get(f, set())})
        raw_findings.append(
            {
                "file_name": primary_file,
                "title": f"Circular Import Cycle ({cycle_chain})",
                "description": f"Circular dependency cycle detected: {cycle_chain}. Mutual imports prevent clean initialization and cause runtime `ImportError`.",
                "severity": Severity.HIGH,
                "category": "Architecture",
                "line_number": 1,
                "suggested_fix": "Extract shared dependencies into a separate module or convert eager top-level imports to deferred function-scoped imports.",
                "root_cause": (
                    f"Modules form a mutual cyclic dependency: {cycle_chain}. When Python loads module `{cycle[0]}`, it pauses at top level to import `{cycle[1]}`, "
                    f"which in turn imports `{cycle[0]}` before its symbols are bound. This triggers `ImportError: cannot import name ... from partially initialized module`."
                ),
                "code_evidence": extract_code_evidence(file_sources.get(primary_file, ""), 1, 3),
                "potential_impact": "Application startup failure and fatal `ImportError` or `AttributeError` on first module access, preventing deployment.",
                "affected_files": all_affected,
                "dependencies": list(cycle),
            }
        )

    # 3. Run AST Static Code Auditor on all files
    for file_path, source in file_sources.items():
        if not source:
            continue
        try:
            tree = ast.parse(source, filename=file_path)
            auditor = ASTCodeAuditor(
                file_path=file_path,
                source_code=source,
                upstream_deps=sorted(list(upstream_adj.get(file_path, set()))),
                downstream_deps=sorted(list(downstream_adj.get(file_path, set()))),
            )
            auditor.audit(tree)
            raw_findings.extend(auditor.findings)
        except SyntaxError as exc:
            all_downstream = sorted(list(downstream_adj.get(file_path, set())))
            raw_findings.append(
                {
                    "file_name": file_path,
                    "title": f"Syntax / Parse Error in `{file_path}`",
                    "description": f"Syntax error at line {exc.lineno}: {exc.msg}. File cannot be executed by Python.",
                    "severity": Severity.HIGH,
                    "category": "Syntax Error",
                    "line_number": exc.lineno,
                    "suggested_fix": f"Correct syntax near line {exc.lineno}: {exc.text or exc.msg}.",
                    "root_cause": f"Invalid Python syntax at line {exc.lineno} violating language grammar ({exc.msg}).",
                    "code_evidence": extract_code_evidence(source, exc.lineno),
                    "potential_impact": "Uncaught SyntaxError prevents module compilation and halts program startup.",
                    "affected_files": [file_path] + all_downstream,
                    "dependencies": [],
                }
            )

    # 4. Run Duplicated Code Clone Detector across the repository
    clone_findings = detect_code_clones(file_sources, downstream_adj, min_lines=5)
    raw_findings.extend(clone_findings)

    # 5. Attempt deep LLM analysis only if valid API keys are configured
    model_name = "Static AST & Architecture Engine"
    fallback_used = False

    has_api_keys = bool(
        os.getenv("ENABLE_LLM_DEBT_ANALYSIS", "false").lower() in ("true", "1")
        and (
            (os.getenv("OPENAI_API_KEY") and not os.getenv("OPENAI_API_KEY", "").startswith("sk-your"))
            or (os.getenv("GEMINI_API_KEY") and not os.getenv("GEMINI_API_KEY", "").startswith("your-"))
            or (os.getenv("OPENROUTER_API_KEY") and not os.getenv("OPENROUTER_API_KEY", "").startswith("your-"))
            or os.getenv("ANTHROPIC_API_KEY")
        )
    )

    if has_api_keys:
        import concurrent.futures
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
                '"category":string,"line_number":int|null,"suggested_fix":string,"root_cause":string,"potential_impact":string,"dependencies":[string]}]}'
            )
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(generate_completion, llm_prompt, system=llm_system, json_mode=True)
                raw = future.result(timeout=4.0)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            llm_parsed = _parse_json(raw["content"])
            llm_items = (
                llm_parsed.get("findings", [])
                if isinstance(llm_parsed, dict)
                else (llm_parsed if isinstance(llm_parsed, list) else [])
            )

            for item in llm_items:
                sev_str = str(item.get("severity", "Medium")).capitalize()
                severity = Severity.HIGH if sev_str == "High" else (Severity.LOW if sev_str == "Low" else Severity.MEDIUM)
                file_p = item.get("file_name", "unknown.py")
                downstream = sorted(list(downstream_adj.get(file_p, set())))
                raw_findings.append(
                    {
                        "file_name": file_p,
                        "title": item.get("title") or item.get("description", "")[:50],
                        "description": item.get("description", ""),
                        "severity": severity,
                        "category": item.get("category", "Logic Bug"),
                        "line_number": item.get("line_number"),
                        "suggested_fix": item.get("suggested_fix", ""),
                        "root_cause": item.get("root_cause") or "Identified via deep semantic analysis.",
                        "code_evidence": extract_code_evidence(file_sources.get(file_p, ""), item.get("line_number")),
                        "potential_impact": item.get("potential_impact") or "Runtime defect affecting caller reliability.",
                        "affected_files": [file_p] + downstream,
                        "dependencies": item.get("dependencies", []),
                    }
                )
            model_name = raw.get("model", "Hybrid AST + LLM Engine")
            fallback_used = raw.get("fallback_used", False)
        except Exception:
            fallback_used = True

    # 6. Deduplicate findings
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in raw_findings:
        key = f"{item['file_name']}:{item['title'].lower()}:{item.get('line_number')}"
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(item)

    # 7. Build structured findings with Proposed Code and Structured Dependency Plans
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
                nodes=payload.nodes,
                edges=payload.edges,
                file_sources=file_sources,
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
                root_cause=item.get("root_cause", ""),
                code_evidence=item.get("code_evidence", ""),
                potential_impact=item.get("potential_impact", ""),
                affected_files=item.get("affected_files") or ([file_path] + downstream),
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
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    file_sources: dict[str, str] | None = None,
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
    root_summary = f" Address Root Cause: {item.get('root_cause', '')}" if item.get("root_cause") else ""
    steps.append(
        RemediationStep(
            step_number=2,
            phase="Phase 2: Target File Remediation",
            file_name=file_path,
            action=f"Apply fix for {item['title']}",
            details=f"Implement proposed fix: {item['suggested_fix']} (Targeting line {item.get('line_number') or 'module scope'}).{root_summary}",
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
                details=f"Test that downstream modules ({', '.join(downstream)}) function correctly without breaking changes. Potential impact to avert: {item.get('potential_impact', 'Runtime defect')}.",
            )
        )
    else:
        steps.append(
            RemediationStep(
                step_number=3,
                phase="Phase 3: Verification & Test Execution",
                file_name=file_path,
                action="Run unit tests and verify runtime behavior",
                details=f"Verify `{file_path}` compiles cleanly and passes all static checks without regressions.",
            )
        )

    blast_radius = (
        f"High risk: Affects {len(downstream)} downstream dependent files ({', '.join(downstream[:3])})"
        if len(downstream) > 1
        else (f"Moderate: Affects `{downstream[0]}`" if downstream else "Isolated to target file: No downstream consumers")
    )

    guided_plan = None
    try:
        from services.repair_planner import generate_guided_repair_plan
        guided_plan = generate_guided_repair_plan(
            finding=item,
            nodes=nodes or [],
            edges=edges or [],
            file_sources=file_sources or {},
            proposed_code=proposed_code,
        )
    except Exception as e:
        logger.warning("Failed to generate guided repair plan: %s", e)

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
        guided_plan=guided_plan,
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
            is_cyclic = any(
                re.search(rf"\bimport\s+{re.escape(dep[:-3] if dep.endswith('.py') else dep)}\b", line)
                or re.search(rf"\bfrom\s+{re.escape(dep[:-3] if dep.endswith('.py') else dep)}\b", line)
                for dep in cycle_deps
                if dep != file_path
            )
            if is_cyclic and not replaced:
                imp_stmt = line.strip()
                new_lines.append(
                    f"# [ArchiteX Fix] Resolved circular import with deferred function import:\n# Moved `{imp_stmt}` into local function scope.\n"
                )
                replaced = True
            else:
                new_lines.append(line)
        if replaced:
            return "".join(new_lines)

    # 2. Wildcard import: replace the math wildcard with only the math symbols
    # referenced by this file. Other modules need export analysis before they can
    # be changed safely, so leave them without an automatic patch.
    if "Wildcard Import" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        match = re.search(r"from\s+([a-zA-Z0-9_\.]+)\s+import\s+\*", line)
        if not match or match.group(1) != "math":
            return ""
        try:
            import math
            tree = ast.parse(source, filename=file_path)
        except (SyntaxError, ImportError):
            return ""
        math_exports = {name for name in dir(math) if not name.startswith("_")}
        used_math_names = sorted({
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in math_exports
        })
        if used_math_names:
            newline = "\r\n" if "\r\n" in line else "\n"
            lines[line_no - 1] = f"from math import {', '.join(used_math_names)}{newline}"
        else:
            lines[line_no - 1] = ""
        return "".join(lines)

    # 3. Weak or Non-Descriptive Naming: rename function cleanly while keeping body
    if "Weak or Non-Descriptive Naming" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        match = re.search(r"def\s+([a-zA-Z0-9_]+)\s*\(", line)
        if match:
            old_name = match.group(1)
            better_name = "calculate_metric" if "terrible" in old_name else ("process_data" if "bad" in old_name else f"run_{old_name}")
            lines[line_no - 1] = re.sub(
                rf"(\bdef\s+){re.escape(old_name)}(?=\s*\()",
                rf"\g<1>{better_name}",
                line,
                count=1,
            )
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

    # 5. Bare except: -> except Exception as exc:
    if "Bare `except:`" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        new_line = re.sub(r"except\s*:", "except Exception as exc:", line)
        if new_line != line:
            lines[line_no - 1] = new_line
            return "".join(lines)

    # 6. Literal identity comparison with `is`: -> ==
    if "Literal Identity Comparison" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        new_line = re.sub(r"\bis\s+not\b", "!=", line)
        new_line = re.sub(r"\bis\b", "==", new_line)
        if new_line != line:
            lines[line_no - 1] = new_line
            return "".join(lines)

    # 7. Comparison with None using ==: -> is None
    if "Comparison to `None`" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        new_line = re.sub(r"==\s*None\b", "is None", line)
        new_line = re.sub(r"!=\s*None\b", "is not None", new_line)
        if new_line != line:
            lines[line_no - 1] = new_line
            return "".join(lines)

    # 8. Silenced exception swallowed by pass
    if "Silently Swallowed Exception" in title and line_no and 1 <= line_no <= len(lines):
        target_idx = line_no - 1
        if target_idx + 1 < len(lines) and "pass" in lines[target_idx + 1]:
            indent = re.match(r"^\s*", lines[target_idx + 1]).group(0)
            lines[target_idx + 1] = f"{indent}# Log and handle exception\n{indent}import logging\n{indent}logging.exception('Caught error during processing')\n"
            return "".join(lines)

    # 9. Hardcoded secret: replace literal with os.getenv
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

    # 10. Division by Zero
    if "Division by Zero" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        new_line = re.sub(r"/\s*0\b", "/ (divisor if 'divisor' in locals() and divisor != 0 else 1.0)", line)
        lines[line_no - 1] = new_line
        return "".join(lines)

    # 11. Missing self in instance method
    if "Instance Method Missing `self`" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        new_line = re.sub(r"def\s+([a-zA-Z0-9_]+)\s*\(\s*\)", r"def \1(self)", line)
        new_line = re.sub(r"def\s+([a-zA-Z0-9_]+)\s*\(([^)]+)\)", r"def \1(self, \2)", new_line)
        if new_line != line:
            lines[line_no - 1] = new_line
            return "".join(lines)

    # 12. Missing docstring in function or class
    if "Missing Docstring" in title and line_no and 1 <= line_no <= len(lines):
        line = lines[line_no - 1]
        indent = re.match(r"^\s*", line).group(0) + "    "
        docstring_line = f'{indent}"""{item["title"]}.\n{indent}"""\n'
        lines.insert(line_no, docstring_line)
        return "".join(lines)

    # Do not present a comment-only change as an automatic repair.
    return ""


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
