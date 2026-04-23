from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.evidence import CodeFactsExtractionService
from tools.generation.evidence.models import CodeFactsScope, TargetStack


class CodeFactsExtractionServiceTests(unittest.TestCase):
    def test_selects_python_extractor_for_python_scope(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "app.py"
            source.write_text("from fastapi import APIRouter\nrouter=APIRouter()\n", encoding="utf-8")

            result = CodeFactsExtractionService().select_extractor(
                root,
                CodeFactsScope(scope_id="api", paths=[Path("app.py")]),
            )

        self.assertEqual(result.selected_stack, TargetStack.PYTHON)
        self.assertEqual(result.diagnostics, [])

    def test_selects_java_spring_extractor_for_spring_controller_scope(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "UserController.java"
            source.write_text(
                "\n".join(
                    [
                        "import org.springframework.web.bind.annotation.*;",
                        "@RestController",
                        "public class UserController {",
                        '  @GetMapping("/users/{id}")',
                        "  public String getUser() { return \"ok\"; }",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )

            result = CodeFactsExtractionService().select_extractor(
                root,
                CodeFactsScope(scope_id="api", paths=[Path("UserController.java")]),
            )

        self.assertEqual(result.selected_stack, TargetStack.JAVA_SPRING)
        self.assertEqual(result.diagnostics, [])

    def test_mixed_scope_is_reported_as_ambiguous(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('x')\n", encoding="utf-8")
            (root / "UserController.java").write_text("@RestController class UserController {}\n", encoding="utf-8")

            result = CodeFactsExtractionService().select_extractor(
                root,
                CodeFactsScope(
                    scope_id="api",
                    paths=[Path("app.py"), Path("UserController.java")],
                ),
            )

        self.assertIsNone(result.selected_stack)
        self.assertTrue(any(diagnostic.code == "ambiguous_stack" for diagnostic in result.diagnostics))

    def test_unsupported_stack_is_reported_without_running_wrong_extractor(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "controller.ts"
            source.write_text("export const controller = {};\n", encoding="utf-8")

            bundle = CodeFactsExtractionService().extract(
                root,
                CodeFactsScope(scope_id="api", paths=[Path("controller.ts")]),
            )

        self.assertEqual(bundle.facts, [])
        self.assertTrue(any(diagnostic.code == "unsupported_stack" for diagnostic in bundle.diagnostics))

    def test_explicit_stack_hint_mismatch_is_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "UserController.java"
            source.write_text("@RestController class UserController {}\n", encoding="utf-8")

            bundle = CodeFactsExtractionService().extract(
                root,
                CodeFactsScope(
                    scope_id="api",
                    paths=[Path("UserController.java")],
                    stack_hint=TargetStack.PYTHON,
                ),
            )

        self.assertEqual(bundle.facts, [])
        self.assertTrue(any(diagnostic.code == "extractor_not_applicable" for diagnostic in bundle.diagnostics))


if __name__ == "__main__":
    unittest.main()
