"""Typed code facts and evidence extraction for generation workflows."""

from .api_surface import PythonApiSurfaceFactsExtractor
from .extractors import CodeFactsExtractor
from .java_spring_api_surface import JavaSpringApiSurfaceFactsExtractor
from .models import (
    CodeFactsScope,
    EvidenceConfidence,
    EvidenceProvenance,
    GenerationEvidenceBundle,
    GenerationEvidenceFact,
    TargetStack,
)
from .services import CodeFactsExtractionService, ExtractorSelectionResult

__all__ = [
    "CodeFactsExtractionService",
    "CodeFactsExtractor",
    "CodeFactsScope",
    "EvidenceConfidence",
    "EvidenceProvenance",
    "ExtractorSelectionResult",
    "GenerationEvidenceBundle",
    "GenerationEvidenceFact",
    "JavaSpringApiSurfaceFactsExtractor",
    "PythonApiSurfaceFactsExtractor",
    "TargetStack",
]
