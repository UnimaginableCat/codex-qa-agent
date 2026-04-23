from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.domain.models import DiagnosticSeverity
from tools.generation.evidence.java_spring_api_surface import JavaSpringApiSurfaceFactsExtractor
from tools.generation.evidence.models import CodeFactsScope, EvidenceConfidence


class JavaSpringApiSurfaceFactsExtractorTests(unittest.TestCase):
    def test_extracts_controller_routes_with_class_and_method_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "main" / "java" / "demo" / "UserController.java"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        "import org.springframework.web.bind.annotation.*;",
                        "",
                        "@RestController",
                        '@RequestMapping("/api/users")',
                        "public class UserController {",
                        '    @GetMapping("/{id}")',
                        "    public UserDto getUser(@PathVariable String id) { return null; }",
                        "",
                        '    @PostMapping(path = "")',
                        "    public UserDto createUser(@RequestBody CreateUserRequest request) { return null; }",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )

            bundle = JavaSpringApiSurfaceFactsExtractor().extract(
                root,
                CodeFactsScope(scope_id="api", paths=[Path("src/main/java/demo/UserController.java")]),
            )

        facts_by_path = {fact.payload["endpoint_path"]: fact for fact in bundle.facts}
        self.assertIn("/api/users/{id}", facts_by_path)
        self.assertIn("/api/users", facts_by_path)
        get_user = facts_by_path["/api/users/{id}"]
        create_user = facts_by_path["/api/users"]
        self.assertEqual(get_user.payload["http_method"], "GET")
        self.assertEqual(create_user.payload["http_method"], "POST")
        self.assertEqual(create_user.payload["handler_name"], "createUser")
        self.assertEqual(create_user.payload["controller_name"], "UserController")
        self.assertTrue(create_user.payload["request_type_present"])
        self.assertTrue(create_user.payload["response_type_present"])
        self.assertEqual(create_user.confidence, EvidenceConfidence.EXPLICIT)
        self.assertEqual(create_user.provenance.file_path, Path("src/main/java/demo/UserController.java"))

    def test_request_mapping_without_method_adds_partial_diagnostic(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "DemoController.java"
            source.write_text(
                "\n".join(
                    [
                        "import org.springframework.web.bind.annotation.*;",
                        "@RestController",
                        "public class DemoController {",
                        '  @RequestMapping("/legacy")',
                        "  public String legacy() { return \"ok\"; }",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )

            bundle = JavaSpringApiSurfaceFactsExtractor().extract(
                root,
                CodeFactsScope(scope_id="api", paths=[Path("DemoController.java")]),
            )

        self.assertEqual(bundle.facts[0].payload["http_method"], None)
        self.assertEqual(bundle.facts[0].confidence, EvidenceConfidence.STRONG_INFERENCE)
        self.assertTrue(
            any(
                diagnostic.code == "partial_extraction_missing_http_method"
                and diagnostic.severity == DiagnosticSeverity.WARNING
                for diagnostic in bundle.diagnostics
            )
        )


if __name__ == "__main__":
    unittest.main()
