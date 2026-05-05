"""Readiness metadata diagnostics for compact authoring cases."""

from __future__ import annotations

from typing import Any

from tools.generation.domain.models import GenerationDiagnostic

from ..diagnostics import authoring_diagnostic
from ..models import AuthoringCase


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
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return True
        if isinstance(value, dict) and any(str(item).strip() for item in value.values()):
            return True
    return False
