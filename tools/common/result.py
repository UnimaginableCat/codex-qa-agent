"""Shared execution result model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .json_safe import to_json_safe
from .statuses import StepStatus


@dataclass(slots=True)
class ExecutionResult:
    """Structured execution result for CLI-oriented tools."""

    status: StepStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status.value,
            "message": self.message,
        }

        for key, value in self.details.items():
            if value is not None:
                payload[key] = to_json_safe(value)

        return payload
