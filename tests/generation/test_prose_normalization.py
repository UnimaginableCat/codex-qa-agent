from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.generation.domain.models import GenerationSourceInput, SourceInputFormat
from tools.generation.normalization.prose import ProseSourceNormalizer


class ProseSourceNormalizerTests(unittest.TestCase):
    def test_russian_prose_splits_into_conservative_cases(self) -> None:
        result = ProseSourceNormalizer().normalize(
            GenerationSourceInput(source_id="users", project="code/demo"),
            "Проверить создание пользователя, валидацию email, получение пользователя по id и ошибку при несуществующем id",
        )

        self.assertEqual([draft.draft_id for draft in result.normalized_source.test_case_drafts], ["tc-001", "tc-002", "tc-003", "tc-004"])
        self.assertEqual(result.normalized_source.test_case_drafts[0].title, "Создание пользователя")
        self.assertIn("negative", result.normalized_source.test_case_drafts[-1].tags)
        self.assertTrue(any(diagnostic.code == "ambiguous_prose_split" for diagnostic in result.diagnostics))

    def test_structured_input_format_is_reported_as_unsupported_for_now(self) -> None:
        result = ProseSourceNormalizer().normalize(
            GenerationSourceInput(
                source_id="structured",
                project="code/demo",
                input_format=SourceInputFormat.STRUCTURED,
            ),
            '{"cases": []}',
        )

        self.assertEqual(result.normalized_source.test_case_drafts, [])
        self.assertEqual(result.diagnostics[0].code, "unsupported_source_format")

    def test_broad_negative_case_adds_open_question(self) -> None:
        result = ProseSourceNormalizer().normalize(
            GenerationSourceInput(source_id="price-list", project="code/demo"),
            "Проверить happy path и негативные кейсы для создания прайс-листа",
        )

        negative_case = result.normalized_source.test_case_drafts[-1]

        self.assertTrue(negative_case.open_questions)
        self.assertTrue(any(diagnostic.code == "ambiguous_prose" for diagnostic in result.diagnostics))


if __name__ == "__main__":
    unittest.main()

