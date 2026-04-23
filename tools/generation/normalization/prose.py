"""Deterministic prose-first normalization for generation source input."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tools.generation.domain.models import (
    DiagnosticSeverity,
    GenerationDiagnostic,
    GenerationSourceInput,
    NormalizedProseSource,
    ProseTestCaseDraft,
    SourceInputFormat,
)


@dataclass(slots=True)
class ProseNormalizationResult:
    normalized_source: NormalizedProseSource
    diagnostics: list[GenerationDiagnostic] = field(default_factory=list)


class ProseSourceNormalizer:
    """Build a conservative normalized source model from operator prose."""

    _unsupported_markers = (
        "markdown scenario",
        "scenario markdown",
        "runnable scenario",
        "execute scenario",
        "run scenario",
        "сценарий markdown",
        "markdown сценарий",
        "запусти сценар",
    )
    _high_priority_markers = (
        "critical",
        "high priority",
        "p0",
        "p1",
        "критич",
        "важн",
        "высок",
    )
    _low_priority_markers = ("low priority", "p3", "низк")
    _negative_markers = (
        "invalid",
        "missing",
        "not found",
        "error",
        "negative",
        "несуществ",
        "ошиб",
        "негатив",
        "невалид",
        "отсутств",
    )
    _section_names = {
        "preconditions": "preconditions",
        "предусловия": "preconditions",
        "steps": "steps",
        "шаги": "steps",
        "expected": "expected",
        "expected results": "expected",
        "ожидания": "expected",
        "ожидаемый результат": "expected",
        "assumptions": "assumptions",
        "допущения": "assumptions",
        "open questions": "open_questions",
        "questions": "open_questions",
        "вопросы": "open_questions",
    }

    def normalize(self, source_input: GenerationSourceInput, content: str) -> ProseNormalizationResult:
        diagnostics: list[GenerationDiagnostic] = []
        normalized_text = _normalize_text(content)
        title = _derive_title(source_input, normalized_text)

        if source_input.input_format != SourceInputFormat.PROSE:
            diagnostics.append(
                GenerationDiagnostic(
                    code="unsupported_source_format",
                    message="Only prose source input is supported in this generation phase.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_input.source_id,
                    details={"input_format": source_input.input_format.value},
                )
            )
            return ProseNormalizationResult(
                normalized_source=NormalizedProseSource(
                    source_id=source_input.source_id,
                    project=source_input.project,
                    title=title,
                    normalized_text=normalized_text,
                ),
                diagnostics=diagnostics,
            )

        if not normalized_text:
            diagnostics.append(
                GenerationDiagnostic(
                    code="source_content_empty",
                    message="Prose source input has no content to normalize.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_input.source_id,
                )
            )
            return ProseNormalizationResult(
                normalized_source=NormalizedProseSource(
                    source_id=source_input.source_id,
                    project=source_input.project,
                    title=title,
                    normalized_text=normalized_text,
                ),
                diagnostics=diagnostics,
            )

        unsupported_mentions = [
            marker for marker in self._unsupported_markers if marker in normalized_text.lower()
        ]
        if unsupported_mentions:
            diagnostics.append(
                GenerationDiagnostic(
                    code="unsupported_construct_current_phase",
                    message="Source asks for scenario rendering or execution, which is out of scope for Phase 1.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=source_input.source_id,
                    details={"markers": unsupported_mentions},
                )
            )

        explicit_sections = _extract_inline_sections(normalized_text)
        clauses, used_fallback_split = _extract_case_clauses(normalized_text)
        if used_fallback_split and len(clauses) > 1:
            diagnostics.append(
                GenerationDiagnostic(
                    code="ambiguous_prose_split",
                    message="Prose was split into candidate test cases using simple separators.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=source_input.source_id,
                    details={"case_count": len(clauses)},
                )
            )

        if not clauses:
            diagnostics.append(
                GenerationDiagnostic(
                    code="no_test_cases_detected",
                    message="No actionable test case intent could be detected from the prose input.",
                    severity=DiagnosticSeverity.ERROR,
                    source_ref=source_input.source_id,
                )
            )

        drafts: list[ProseTestCaseDraft] = []
        plan_assumptions: list[str] = []
        plan_open_questions: list[str] = []
        for index, clause in enumerate(clauses, start=1):
            draft, case_diagnostics = self._build_case_draft(
                source_input=source_input,
                title=title,
                clause=clause,
                index=index,
                explicit_sections=explicit_sections,
            )
            drafts.append(draft)
            diagnostics.extend(case_diagnostics)
            plan_assumptions.extend(draft.assumptions)
            plan_open_questions.extend(draft.open_questions)

        normalized_source = NormalizedProseSource(
            source_id=source_input.source_id,
            project=source_input.project,
            title=title,
            normalized_text=normalized_text,
            test_case_drafts=drafts,
            assumptions=_dedupe(plan_assumptions),
            open_questions=_dedupe(plan_open_questions),
            metadata={
                "normalizer": "prose-rule-v1",
                "input_format": source_input.input_format.value,
                "case_detection": "separator_split" if used_fallback_split else "explicit_or_single",
            },
        )
        return ProseNormalizationResult(normalized_source=normalized_source, diagnostics=diagnostics)

    def _build_case_draft(
        self,
        *,
        source_input: GenerationSourceInput,
        title: str,
        clause: str,
        index: int,
        explicit_sections: dict[str, list[str]],
    ) -> tuple[ProseTestCaseDraft, list[GenerationDiagnostic]]:
        diagnostics: list[GenerationDiagnostic] = []
        source_ref = f"{source_input.source_id}#case-{index:03d}"
        priority = _derive_priority(clause, self._high_priority_markers, self._low_priority_markers)
        case_title = _build_case_title(clause, title)
        objective = _build_objective(clause)
        assumptions = list(explicit_sections.get("assumptions", []))
        open_questions = list(explicit_sections.get("open_questions", []))

        preconditions = list(explicit_sections.get("preconditions", []))
        steps = list(explicit_sections.get("steps", [])) or [f"Exercise behavior described as: {clause}"]
        expected_results = list(explicit_sections.get("expected", []))
        if not expected_results:
            expected_results = [_default_expected_result(clause, self._negative_markers)]
            assumption = "Expected result was inferred from prose because no explicit expected outcome was provided."
            assumptions.append(assumption)
            diagnostics.append(
                GenerationDiagnostic(
                    code="inferred_assumption",
                    message=assumption,
                    severity=DiagnosticSeverity.INFO,
                    source_ref=source_ref,
                )
            )

        if not _has_executable_detail(clause):
            question = "Which concrete API, UI action, data setup, or DB check should validate this case?"
            open_questions.append(question)
            diagnostics.append(
                GenerationDiagnostic(
                    code="incomplete_testable_detail",
                    message="Planned case lacks concrete executable detail for scenario rendering.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=source_ref,
                    details={"case_title": case_title},
                )
            )

        if _is_broad_negative_bucket(clause):
            question = "Which specific negative inputs, statuses, or missing entities should be covered?"
            open_questions.append(question)
            diagnostics.append(
                GenerationDiagnostic(
                    code="ambiguous_prose",
                    message="Negative-case wording is broad and needs operator clarification.",
                    severity=DiagnosticSeverity.WARNING,
                    source_ref=source_ref,
                    details={"case_title": case_title},
                )
            )

        tags = _derive_tags(clause, self._negative_markers)
        draft = ProseTestCaseDraft(
            draft_id=f"tc-{index:03d}",
            title=case_title,
            objective=objective,
            source_ref=source_ref,
            preconditions=preconditions,
            steps=steps,
            expected_results=expected_results,
            priority=priority,
            assumptions=_dedupe(assumptions),
            open_questions=_dedupe(open_questions),
            tags=tags,
        )
        return draft, diagnostics


def _normalize_text(content: str) -> str:
    lines = [line.strip() for line in str(content).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    compact_lines: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        compact_lines.append(line)
        previous_blank = is_blank
    return "\n".join(compact_lines).strip()


def _derive_title(source_input: GenerationSourceInput, normalized_text: str) -> str:
    if source_input.name.strip():
        return source_input.name.strip()
    for line in normalized_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if heading:
            return heading.group(1).strip()
        return _strip_source_prefix(stripped).strip(" .:-")[:120] or source_input.source_id
    return source_input.source_id


def _extract_inline_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        section_match = re.match(r"^(?:#{1,6}\s*)?([A-Za-zА-Яа-яёЁ ]{3,40})\s*:\s*(.*)$", line)
        if section_match:
            normalized_name = section_match.group(1).strip().lower()
            current = ProseSourceNormalizer._section_names.get(normalized_name)
            remainder = section_match.group(2).strip()
            if current is not None and remainder:
                sections.setdefault(current, []).append(remainder)
            continue
        bullet_match = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)$", line)
        if current is not None and bullet_match:
            sections.setdefault(current, []).append(bullet_match.group(1).strip())
    return {key: _dedupe(values) for key, values in sections.items()}


def _extract_case_clauses(text: str) -> tuple[list[str], bool]:
    explicit = _extract_explicit_case_blocks(text)
    if explicit:
        return explicit, False

    single_line = " ".join(line.strip("#- *\t ") for line in text.splitlines() if line.strip())
    source = _strip_source_prefix(single_line)
    if ":" in source:
        before, after = source.split(":", 1)
        source = after if len(after.strip()) >= 4 else before
    separators = r",|;|\s+\b(?:and|и|а также)\b\s+"
    parts = [part.strip(" .:-") for part in re.split(separators, source, flags=re.IGNORECASE)]
    clauses = [part for part in parts if len(part) >= 3]
    if len(clauses) == 1 and len(clauses[0].split()) > 18:
        return [clauses[0]], True
    return _dedupe(clauses), True


def _extract_explicit_case_blocks(text: str) -> list[str]:
    clauses: list[str] = []
    current: list[str] = []
    case_heading_re = re.compile(
        r"^(?:#{1,6}\s*)?(?:case|test|scenario|кейс|тест|сценарий)\s*\d*[:.)-]?\s*(.*)$",
        re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = case_heading_re.match(line)
        if match:
            if current:
                clauses.append(" ".join(current).strip())
            current = [match.group(1).strip() or line.strip("# ")]
            continue
        if current:
            current.append(line.strip("-* "))
    if current:
        clauses.append(" ".join(current).strip())
    return [clause for clause in clauses if clause]


def _strip_source_prefix(text: str) -> str:
    prefixes = (
        r"проверить\s+",
        r"нужно\s+проверить\s+",
        r"нужен\s+тест[- ]план\s+на\s+",
        r"нужны\s+тесты\s+на\s+",
        r"need\s+(?:a\s+)?test\s+plan\s+(?:for|on)\s+",
        r"test\s+plan\s+(?:for|on)\s+",
        r"verify\s+",
        r"check\s+",
    )
    stripped = text.strip()
    for prefix in prefixes:
        stripped = re.sub(rf"^{prefix}", "", stripped, flags=re.IGNORECASE)
    return stripped.strip()


def _derive_priority(text: str, high_markers: tuple[str, ...], low_markers: tuple[str, ...]) -> str:
    lower = text.lower()
    if any(marker in lower for marker in high_markers):
        return "high"
    if any(marker in lower for marker in low_markers):
        return "low"
    return "normal"


def _build_case_title(clause: str, plan_title: str) -> str:
    cleaned = clause.strip(" .:-")
    if not cleaned:
        return plan_title
    return cleaned[:1].upper() + cleaned[1:]


def _build_objective(clause: str) -> str:
    return f"Verify {clause.strip(' .:-')}."


def _default_expected_result(clause: str, negative_markers: tuple[str, ...]) -> str:
    lower = clause.lower()
    if any(marker in lower for marker in negative_markers):
        return "System handles the negative condition with a clear error or empty-result behavior."
    return "System behavior matches the requested outcome described in the source prose."


def _has_executable_detail(clause: str) -> bool:
    lower = clause.lower()
    markers = (
        "api",
        "endpoint",
        "request",
        "response",
        "db",
        "sql",
        "create",
        "get",
        "list",
        "patch",
        "delete",
        "post",
        "put",
        "создан",
        "создание",
        "получ",
        "валидац",
        "ошиб",
        "id",
    )
    return any(marker in lower for marker in markers)


def _is_broad_negative_bucket(clause: str) -> bool:
    lower = clause.lower()
    return ("negative" in lower or "негатив" in lower) and not any(
        marker in lower for marker in ("invalid", "missing", "несуществ", "невалид", "отсутств")
    )


def _derive_tags(clause: str, negative_markers: tuple[str, ...]) -> list[str]:
    tags: list[str] = []
    lower = clause.lower()
    if any(marker in lower for marker in negative_markers):
        tags.append("negative")
    if any(marker in lower for marker in ("happy path", "успеш", "success")):
        tags.append("happy-path")
    return tags


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result

