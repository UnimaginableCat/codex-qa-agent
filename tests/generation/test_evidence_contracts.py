from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.domain.models import DiagnosticSeverity, GenerationDiagnostic
from tools.generation.evidence.models import (
    CodeFactsScope,
    EvidenceConfidence,
    EvidenceProvenance,
    GenerationEvidenceBundle,
    GenerationEvidenceFact,
)


class EvidenceContractTests(unittest.TestCase):
    def test_evidence_bundle_round_trips_through_json_payload(self) -> None:
        bundle = GenerationEvidenceBundle(
            bundle_id="evidence-api",
            target_project="code/demo",
            scope="api",
            facts=[
                GenerationEvidenceFact(
                    fact_id="api-users-get",
                    fact_type="api_endpoint",
                    summary="GET /users/{user_id} handled by get_user",
                    payload={
                        "endpoint_path": "/users/{user_id}",
                        "http_method": "GET",
                        "handler_name": "get_user",
                    },
                    provenance=EvidenceProvenance(
                        source_kind="python_ast",
                        file_path=Path("app/api.py"),
                        symbol="get_user",
                        line_range=(10, 12),
                        notes="decorator",
                    ),
                    confidence=EvidenceConfidence.EXPLICIT,
                    related_interfaces=["/users/{user_id}"],
                )
            ],
            diagnostics=[
                GenerationDiagnostic(
                    code="partial_extraction_missing_http_method",
                    message="partial",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref="api",
                )
            ],
            created_at="2026-04-23T08:00:00+00:00",
        )

        payload = json.loads(json.dumps(bundle.to_dict()))
        restored = GenerationEvidenceBundle.from_dict(payload)

        self.assertEqual(restored.bundle_id, "evidence-api")
        self.assertEqual(restored.facts[0].confidence, EvidenceConfidence.EXPLICIT)
        self.assertEqual(restored.facts[0].provenance.file_path, Path("app/api.py"))
        self.assertEqual(restored.facts[0].provenance.line_range, (10, 12))
        self.assertEqual(restored.diagnostics[0].severity, DiagnosticSeverity.WARNING)

    def test_code_facts_scope_round_trips_paths_and_limits(self) -> None:
        scope = CodeFactsScope(
            scope_id="controllers",
            paths=[Path("src/controllers")],
            file_patterns=["*.py"],
            max_files=3,
        )

        restored = CodeFactsScope.from_dict(scope.to_dict())

        self.assertEqual(restored.scope_id, "controllers")
        self.assertEqual(restored.paths, [Path("src/controllers")])
        self.assertEqual(restored.file_patterns, ["*.py"])
        self.assertEqual(restored.max_files, 3)


if __name__ == "__main__":
    unittest.main()
