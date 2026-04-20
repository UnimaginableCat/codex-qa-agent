"""Loaders for report tooling."""

from __future__ import annotations

from pathlib import Path

from tools.common import ValidationError, read_json_file

from .models import SummaryData


class SummaryLoader:
    """Loads and validates summary JSON."""

    def load(self, summary_path: Path) -> SummaryData:
        payload = read_json_file(summary_path, "Summary")
        if not isinstance(payload, dict):
            raise ValidationError("Summary JSON must be an object")

        return SummaryData.from_mapping(payload)
