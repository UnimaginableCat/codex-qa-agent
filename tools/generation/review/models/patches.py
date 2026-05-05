"""Patch template and edit suggestion contract models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tools.common.json_safe import to_json_safe

from .enums import DraftEditTargetType, PatchTemplateType


@dataclass(slots=True)
class PatchTemplate:
    template_id: str
    target_type: DraftEditTargetType
    section_name: str
    title: str
    description: str
    template_lines: list[str] = field(default_factory=list)
    usage_notes: list[str] = field(default_factory=list)
    template_type: PatchTemplateType = PatchTemplateType.SECTION_STUB

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PatchTemplate":
        return cls(
            template_id=str(payload["template_id"]),
            target_type=DraftEditTargetType(str(payload["target_type"])),
            section_name=str(payload["section_name"]),
            title=str(payload["title"]),
            description=str(payload["description"]),
            template_lines=[str(item) for item in payload.get("template_lines", [])],
            usage_notes=[str(item) for item in payload.get("usage_notes", [])],
            template_type=PatchTemplateType(str(payload.get("template_type", PatchTemplateType.SECTION_STUB.value))),
        )

@dataclass(slots=True)
class PatchTemplateCatalog:
    catalog_version: str = "v1"
    templates: list[PatchTemplate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PatchTemplateCatalog":
        return cls(
            catalog_version=str(payload.get("catalog_version", "v1")),
            templates=[PatchTemplate.from_dict(item) for item in payload.get("templates", [])],
        )

@dataclass(slots=True)
class DraftPatchSuggestion:
    template_id: str = ""
    template_preview: list[str] = field(default_factory=list)
    usage_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DraftPatchSuggestion":
        return cls(
            template_id=str(payload.get("template_id", "")),
            template_preview=[str(item) for item in payload.get("template_preview", [])],
            usage_notes=[str(item) for item in payload.get("usage_notes", [])],
        )
