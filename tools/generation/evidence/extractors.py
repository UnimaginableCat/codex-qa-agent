"""Extractor interfaces for targeted code facts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import CodeFactsScope, GenerationEvidenceBundle


class CodeFactsExtractor(Protocol):
    """Targeted code facts extractor contract."""

    def extract(self, project_path: Path, scope: CodeFactsScope) -> GenerationEvidenceBundle:
        """Extract typed evidence from the requested project scope."""
        ...
