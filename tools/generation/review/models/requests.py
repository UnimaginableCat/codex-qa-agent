"""Request contract models for review services."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.common.json_safe import to_json_safe


@dataclass(slots=True)
class ScenarioPromotionRequest:
    run_id: str
    draft_id: str
    workspace_root: Path = Path(".")
    target_dir: Path = Path("scenarios/generated")
    allow_invalid: bool = False
    allow_known_gaps: bool = False
    known_gaps_reviewed: bool = False
    purge_target_dir: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

@dataclass(slots=True)
class ScenarioPromotionBatchRequest:
    run_id: str
    workspace_root: Path = Path(".")
    target_dir: Path = Path("scenarios/generated")
    allow_invalid: bool = False
    allow_known_gaps: bool = False
    known_gaps_reviewed: bool = False
    purge_target_dir: bool = False
    draft_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

@dataclass(slots=True)
class ScenarioRevalidationRequest:
    file_path: Path
    validation_mode: str = "parser"
    workspace_root: Path = Path(".")

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))

@dataclass(slots=True)
class ScenarioDirectoryRevalidationRequest:
    directory_path: Path
    validation_mode: str = "parser"
    workspace_root: Path = Path(".")

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(asdict(self))
