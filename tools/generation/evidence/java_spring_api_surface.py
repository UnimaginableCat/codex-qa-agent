"""Targeted Java/Spring API surface facts extractor for controller source files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.generation.evidence.common import build_evidence_bundle, relative_to_project, resolve_scope_files

from .models import (
    CodeFactsScope,
    EvidenceConfidence,
    EvidenceProvenance,
    GenerationEvidenceFact,
)

_SPRING_CONTROLLER_ANNOTATIONS = {"RestController", "Controller"}
_SPRING_MAPPING_ANNOTATIONS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "PatchMapping": "PATCH",
    "DeleteMapping": "DELETE",
}
_CLASS_RE = re.compile(r"\bclass\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_METHOD_RE = re.compile(
    r"(?:public|protected|private)\s+"
    r"(?P<return_type>[\w<>\[\], ?]+)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\((?P<params>[^)]*)\)"
)
_ANNOTATION_RE = re.compile(r"@(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\((?P<args>.*)\))?$")
_REQUEST_METHOD_RE = re.compile(r"RequestMethod\.(GET|POST|PUT|PATCH|DELETE)")
_NAMED_STRING_ARG_RE = re.compile(r'(?:value|path)\s*=\s*"([^"]*)"')
_FIRST_STRING_RE = re.compile(r'"([^"]*)"')


@dataclass(slots=True)
class JavaSpringApiSurfaceFactsExtractor:
    """Extract Spring controller-level HTTP endpoint facts from explicit Java scope files only."""

    target_stack = "java_spring"

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
                    message="No supported Java/Spring controller mappings were found in scope.",
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
            lines = file_path.read_text(encoding="utf-8").splitlines()
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
        annotation_buffer: list[str] = []
        class_name: str | None = None
        class_base_path = ""
        class_has_controller = False
        brace_depth = 0
        class_brace_depth = 0

        for line_number, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            brace_depth += raw_line.count("{") - raw_line.count("}")
            if stripped.startswith("@"):
                annotation_buffer.append(stripped)
                continue

            class_match = _CLASS_RE.search(stripped)
            if class_match:
                class_name = class_match.group("name")
                class_base_path = _class_level_path(annotation_buffer)
                class_has_controller = _has_controller_annotation(annotation_buffer) or bool(class_base_path)
                class_brace_depth = brace_depth
                annotation_buffer = []
                continue

            method_match = _METHOD_RE.search(stripped)
            if method_match and class_name and class_has_controller and brace_depth >= class_brace_depth:
                method_annotations = list(annotation_buffer)
                annotation_buffer = []
                endpoint_specs = _method_endpoint_specs(method_annotations)
                if not endpoint_specs:
                    continue
                method_name = method_match.group("name")
                params = method_match.group("params")
                return_type = method_match.group("return_type").strip()
                line_range = (line_number, line_number)
                for method_path, http_method, confidence, framework_hint in endpoint_specs:
                    if http_method is None:
                        diagnostics.append(
                            GenerationDiagnostic(
                                code="partial_extraction_missing_http_method",
                                message="Spring mapping path was detected but HTTP method was not explicit.",
                                severity=DiagnosticSeverity.WARNING,
                                source_ref=f"{file_path}:{line_number}",
                                details={"handler": method_name, "path": method_path or class_base_path},
                            )
                        )
                    endpoint_path = _compose_path(class_base_path, method_path)
                    facts.append(
                        _build_endpoint_fact(
                            project_root=project_root,
                            file_path=file_path,
                            class_name=class_name,
                            method_name=method_name,
                            line_range=line_range,
                            path=endpoint_path,
                            http_method=http_method,
                            confidence=confidence,
                            framework_hint=framework_hint,
                            request_type_present="@RequestBody" in params,
                            response_type_present=return_type.lower() != "void",
                        )
                    )
                continue

            if stripped and not stripped.startswith("//") and not stripped.startswith("*"):
                annotation_buffer = []

        return facts


def _build_endpoint_fact(
    *,
    project_root: Path,
    file_path: Path,
    class_name: str,
    method_name: str,
    line_range: tuple[int, int],
    path: str,
    http_method: str | None,
    confidence: EvidenceConfidence,
    framework_hint: str,
    request_type_present: bool,
    response_type_present: bool,
) -> GenerationEvidenceFact:
    relative_file = relative_to_project(file_path, project_root)
    method_label = http_method or "UNKNOWN"
    fact_id = _fact_id(relative_file, class_name, method_name, path, method_label)
    return GenerationEvidenceFact(
        fact_id=fact_id,
        fact_type="api_endpoint",
        summary=f"{method_label} {path} handled by {class_name}.{method_name}",
        payload={
            "endpoint_path": path,
            "http_method": http_method,
            "handler_name": method_name,
            "request_type_present": request_type_present,
            "response_type_present": response_type_present,
            "framework_hint": framework_hint,
            "controller_name": class_name,
        },
        provenance=EvidenceProvenance(
            source_kind="java_spring_annotations",
            file_path=relative_file,
            symbol=f"{class_name}.{method_name}",
            line_range=line_range,
            notes="Extracted from Spring controller mapping annotations.",
        ),
        confidence=confidence,
        related_entities=[class_name],
        related_interfaces=[path],
    )


def _has_controller_annotation(annotations: list[str]) -> bool:
    return any(
        match and match.group("name") in _SPRING_CONTROLLER_ANNOTATIONS
        for match in (_ANNOTATION_RE.match(annotation) for annotation in annotations)
    )


def _class_level_path(annotations: list[str]) -> str:
    for annotation in annotations:
        match = _ANNOTATION_RE.match(annotation)
        if not match or match.group("name") != "RequestMapping":
            continue
        return _extract_mapping_path(match.group("args") or "")
    return ""


def _method_endpoint_specs(
    annotations: list[str],
) -> list[tuple[str, str | None, EvidenceConfidence, str]]:
    specs: list[tuple[str, str | None, EvidenceConfidence, str]] = []
    for annotation in annotations:
        match = _ANNOTATION_RE.match(annotation)
        if not match:
            continue
        annotation_name = match.group("name")
        args = match.group("args") or ""
        if annotation_name in _SPRING_MAPPING_ANNOTATIONS:
            specs.append(
                (
                    _extract_mapping_path(args),
                    _SPRING_MAPPING_ANNOTATIONS[annotation_name],
                    EvidenceConfidence.EXPLICIT,
                    "spring_method_mapping",
                )
            )
            continue
        if annotation_name == "RequestMapping":
            methods = _REQUEST_METHOD_RE.findall(args)
            path = _extract_mapping_path(args)
            if methods:
                for method in methods:
                    specs.append(
                        (
                            path,
                            method,
                            EvidenceConfidence.EXPLICIT,
                            "spring_request_mapping",
                        )
                    )
            else:
                specs.append(
                    (
                        path,
                        None,
                        EvidenceConfidence.STRONG_INFERENCE,
                        "spring_request_mapping",
                    )
                )
    return specs


def _extract_mapping_path(args: str) -> str:
    named = _NAMED_STRING_ARG_RE.search(args)
    if named:
        return named.group(1)
    first = _FIRST_STRING_RE.search(args)
    if first:
        return first.group(1)
    return ""


def _compose_path(base_path: str, method_path: str) -> str:
    base = (base_path or "").strip()
    method = (method_path or "").strip()
    if not base and not method:
        return "/"
    if not base:
        return _normalize_path(method)
    if not method:
        return _normalize_path(base)
    return _normalize_path(f"{base.rstrip('/')}/{method.lstrip('/')}")


def _normalize_path(path: str) -> str:
    normalized = "/" + path.strip().strip("/")
    return normalized if normalized != "//" else "/"


def _fact_id(
    file_path: Path,
    class_name: str,
    method_name: str,
    path: str,
    http_method: str,
) -> str:
    safe = f"{file_path}:{class_name}:{method_name}:{http_method}:{path}"
    return "api-" + "".join(char.lower() if char.isalnum() else "-" for char in safe).strip("-")
