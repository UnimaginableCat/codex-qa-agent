from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.domain.models import DiagnosticSeverity
from tools.generation.evidence.api_surface import ApiSurfaceFactsExtractor
from tools.generation.evidence.models import CodeFactsScope, EvidenceConfidence


class ApiSurfaceFactsExtractorTests(unittest.TestCase):
    def test_extracts_explicit_route_facts_with_provenance(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "app" / "api.py"
            source.parent.mkdir()
            source.write_text(
                "\n".join(
                    [
                        "from fastapi import APIRouter",
                        "router = APIRouter()",
                        "",
                        "@router.get('/users/{user_id}')",
                        "def get_user(user_id: int) -> 'UserResponse':",
                        "    return UserResponse()",
                        "",
                        "@router.route('/legacy')",
                        "def legacy(request):",
                        "    return {}",
                    ]
                ),
                encoding="utf-8",
            )

            bundle = ApiSurfaceFactsExtractor().extract(
                root,
                CodeFactsScope(scope_id="api", paths=[Path("app")]),
            )

        facts_by_path = {fact.payload["endpoint_path"]: fact for fact in bundle.facts}

        self.assertEqual(bundle.scope, "api")
        self.assertIn("/users/{user_id}", facts_by_path)
        get_user = facts_by_path["/users/{user_id}"]
        self.assertEqual(get_user.payload["http_method"], "GET")
        self.assertEqual(get_user.payload["handler_name"], "get_user")
        self.assertTrue(get_user.payload["request_type_present"])
        self.assertTrue(get_user.payload["response_type_present"])
        self.assertEqual(get_user.provenance.file_path, Path("app/api.py"))
        self.assertEqual(get_user.provenance.symbol, "get_user")
        self.assertEqual(get_user.confidence, EvidenceConfidence.EXPLICIT)
        self.assertIn("/users/{user_id}", get_user.related_interfaces)

        legacy = facts_by_path["/legacy"]
        self.assertIsNone(legacy.payload["http_method"])
        self.assertEqual(legacy.confidence, EvidenceConfidence.STRONG_INFERENCE)
        self.assertTrue(
            any(
                diagnostic.code == "partial_extraction_missing_http_method"
                and diagnostic.severity == DiagnosticSeverity.WARNING
                for diagnostic in bundle.diagnostics
            )
        )

    def test_missing_scope_produces_typed_diagnostic_without_global_scan(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle = ApiSurfaceFactsExtractor().extract(
                Path(tmp),
                CodeFactsScope(scope_id="missing"),
            )

        self.assertEqual(bundle.facts, [])
        self.assertTrue(any(diagnostic.code == "missing_evidence_scope" for diagnostic in bundle.diagnostics))

    def test_syntax_error_produces_diagnostic(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.py"
            source.write_text("def broken(:\n", encoding="utf-8")

            bundle = ApiSurfaceFactsExtractor().extract(
                root,
                CodeFactsScope(scope_id="api", paths=[Path("broken.py")]),
            )

        self.assertEqual(bundle.facts, [])
        self.assertTrue(
            any(diagnostic.code == "unsupported_pattern_syntax_error" for diagnostic in bundle.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
