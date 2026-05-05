"""Readiness metadata diagnostics for compact authoring cases."""

from __future__ import annotations

from typing import Any

from tools.generation.domain.models import GenerationDiagnostic

from ..diagnostics import authoring_diagnostic
from ..models import AuthoringCase


_PLACEHOLDER_EVIDENCE_VALUES = {
    "none",
    "null",
    "n/a",
    "na",
    "tbd",
    "todo",
    "unknown",
    "placeholder",
    "{}",
    "[]",
}


def _readiness_metadata_diagnostics(
    case: AuthoringCase,
    case_ref: str,
    *,
    index: int,
) -> list[GenerationDiagnostic]:
    readiness = str(case.metadata.get("readiness") or "").strip().lower()
    if readiness != "evidence_supported" or _has_readiness_evidence(case.metadata):
        return []
    return [
        authoring_diagnostic(
            "authoring_case_readiness_evidence_missing",
            (
                "Case metadata sets readiness=evidence_supported, but does not include concrete readiness "
                "evidence. Do not use readiness metadata only to silence review gaps; add source evidence "
                "or leave the case as route_resolved/deferred until non-route execution details are proven."
            ),
            source_ref=case_ref,
            details={"case_index": index},
        )
    ]


def _has_readiness_evidence(metadata: dict[str, Any]) -> bool:
    for key in ("readiness_evidence", "evidence", "source_evidence", "evidence_refs"):
        if _is_concrete_evidence_value(metadata.get(key)):
            return True
    return False


def _is_concrete_evidence_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return False
        return normalized.lower() not in _PLACEHOLDER_EVIDENCE_VALUES
    if isinstance(value, list):
        return any(_is_concrete_evidence_value(item) for item in value)
    if isinstance(value, dict):
        return any(_is_concrete_evidence_value(item) for item in value.values())
    return False
