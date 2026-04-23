"""Targeted Python API surface facts extractor for Python source files."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.generation.evidence.common import build_evidence_bundle, relative_to_project, resolve_scope_files

from .models import (
    CodeFactsScope,
    EvidenceConfidence,
    EvidenceProvenance,
    GenerationEvidenceFact,
)


@dataclass(slots=True)
class PythonApiSurfaceFactsExtractor:
    """Extract explicit endpoint facts from targeted Python files only."""

    target_stack = "python"

    def extract(self, project_path: Path, scope: CodeFactsScope):
        project_root = project_path.resolve()
        diagnostics: list[GenerationDiagnostic] = []
        facts: list[GenerationEvidenceFact] = []
        files = resolve_scope_files(project_root, scope, diagnostics)

        for file_path in files:
            facts.extend(self._extract_from_file(project_root, file_path, diagnostics))

        if not facts and files:
            diagnostics.append(
                GenerationDiagnostic(
                    code="no_supported_patterns_found",
                    message="No explicit Python API route decorators or path registrations were found in scope.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=scope.scope_id,
                )
            )

        return build_evidence_bundle(
            scope=scope,
            project_root=project_root,
            facts=facts,
            diagnostics=diagnostics,
        )

    def _extract_from_file(
        self,
        project_root: Path,
        file_path: Path,
        diagnostics: list[GenerationDiagnostic],
    ) -> list[GenerationEvidenceFact]:
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            diagnostics.append(
                GenerationDiagnostic(
                    code="unsupported_pattern_syntax_error",
                    message="Python file could not be parsed for API facts.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=str(file_path),
                    details={"line": exc.lineno, "error": str(exc)},
                )
            )
            return []
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                GenerationDiagnostic(
                    code="scope_file_unreadable",
                    message="Evidence scope file could not be read.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=str(file_path),
                    details={"error": str(exc)},
                )
            )
            return []

        facts: list[GenerationEvidenceFact] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                facts.extend(self._facts_from_function(project_root, file_path, node, diagnostics))
            elif isinstance(node, ast.Call):
                fact = self._fact_from_path_registration(project_root, file_path, node)
                if fact is not None:
                    facts.append(fact)
        return facts

    def _facts_from_function(
        self,
        project_root: Path,
        file_path: Path,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        diagnostics: list[GenerationDiagnostic],
    ) -> list[GenerationEvidenceFact]:
        facts: list[GenerationEvidenceFact] = []
        for decorator in node.decorator_list:
            endpoint = _endpoint_from_decorator(decorator)
            if endpoint is None:
                continue
            path, method, confidence, framework_hint = endpoint
            if method is None:
                diagnostics.append(
                    GenerationDiagnostic(
                        code="partial_extraction_missing_http_method",
                        message="Route path was detected but HTTP method was not explicit.",
                        severity=DiagnosticSeverity.WARNING,
                        source_ref=f"{file_path}:{node.lineno}",
                        details={"handler": node.name, "path": path},
                    )
                )
            facts.append(
                self._build_endpoint_fact(
                    project_root=project_root,
                    file_path=file_path,
                    symbol=node.name,
                    line_range=(node.lineno, getattr(node, "end_lineno", node.lineno)),
                    path=path,
                    method=method,
                    confidence=confidence,
                    framework_hint=framework_hint,
                    request_type_present=_has_request_type(node),
                    response_type_present=node.returns is not None,
                )
            )
        return facts

    def _fact_from_path_registration(
        self,
        project_root: Path,
        file_path: Path,
        node: ast.Call,
    ) -> GenerationEvidenceFact | None:
        function_name = _call_name(node.func)
        if function_name not in {"path", "url", "re_path"}:
            return None
        if not node.args:
            return None
        path = _string_value(node.args[0])
        if not path:
            return None
        handler_name = _callable_name(node.args[1]) if len(node.args) > 1 else None
        return self._build_endpoint_fact(
            project_root=project_root,
            file_path=file_path,
            symbol=handler_name,
            line_range=(node.lineno, getattr(node, "end_lineno", node.lineno)),
            path=path,
            method=None,
            confidence=EvidenceConfidence.STRONG_INFERENCE,
            framework_hint="django_urlconf",
            request_type_present=False,
            response_type_present=False,
        )

    @staticmethod
    def _build_endpoint_fact(
        *,
        project_root: Path,
        file_path: Path,
        symbol: str | None,
        line_range: tuple[int, int],
        path: str,
        method: str | None,
        confidence: EvidenceConfidence,
        framework_hint: str,
        request_type_present: bool,
        response_type_present: bool,
    ) -> GenerationEvidenceFact:
        relative_file = relative_to_project(file_path, project_root)
        method_label = method or "UNKNOWN"
        fact_id = _fact_id(relative_file, symbol, path, method_label)
        summary = f"{method_label} {path}"
        if symbol:
            summary += f" handled by {symbol}"
        return GenerationEvidenceFact(
            fact_id=fact_id,
            fact_type="api_endpoint",
            summary=summary,
            payload={
                "endpoint_path": path,
                "http_method": method,
                "handler_name": symbol,
                "request_type_present": request_type_present,
                "response_type_present": response_type_present,
                "framework_hint": framework_hint,
            },
            provenance=EvidenceProvenance(
                source_kind="python_ast",
                file_path=relative_file,
                symbol=symbol,
                line_range=line_range,
                notes="Extracted from explicit route decorator or URL registration.",
            ),
            confidence=confidence,
            related_interfaces=[path],
        )


def _endpoint_from_decorator(
    decorator: ast.expr,
) -> tuple[str, str | None, EvidenceConfidence, str] | None:
    if not isinstance(decorator, ast.Call):
        return None
    call_name = _call_name(decorator.func)
    attr_name = _attr_name(decorator.func)
    if attr_name in {"get", "post", "put", "patch", "delete", "head", "options"}:
        path = _first_string_arg(decorator)
        if path is None:
            return None
        return path, attr_name.upper(), EvidenceConfidence.EXPLICIT, "method_decorator"
    if call_name == "route" or attr_name == "route":
        path = _first_string_arg(decorator)
        if path is None:
            return None
        methods = _methods_keyword(decorator)
        if methods:
            return path, methods[0], EvidenceConfidence.EXPLICIT, "route_decorator"
        return path, None, EvidenceConfidence.STRONG_INFERENCE, "route_decorator"
    return None


def _first_string_arg(call: ast.Call) -> str | None:
    if not call.args:
        return None
    return _string_value(call.args[0])


def _methods_keyword(call: ast.Call) -> list[str]:
    for keyword in call.keywords:
        if keyword.arg != "methods":
            continue
        value = keyword.value
        if isinstance(value, ast.List | ast.Tuple):
            return [
                str(item.value).upper()
                for item in value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
        single = _string_value(value)
        return [single.upper()] if single else []
    return []


def _has_request_type(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for arg in list(node.args.args) + list(node.args.kwonlyargs):
        if arg.annotation is not None:
            return True
        if arg.arg.lower() in {"request", "payload", "body"}:
            return True
    return False


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _attr_name(node: ast.AST) -> str:
    return node.attr if isinstance(node, ast.Attribute) else ""


def _callable_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _fact_id(file_path: Path, symbol: str | None, path: str, method: str) -> str:
    safe = f"{file_path}:{symbol or 'unknown'}:{method}:{path}"
    return "api-" + "".join(char.lower() if char.isalnum() else "-" for char in safe).strip("-")
