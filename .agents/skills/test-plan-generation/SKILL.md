---
name: test-plan-generation
description: Generate a typed NormalizedTestPlan from human-readable prose in the local codex-qa-agent workspace. Use when the user asks to create, normalize, plan, or generate a test plan from a feature/test request description, and the desired output is PlannedTestCase items plus diagnostics/artifacts rather than runnable markdown scenarios or scenario_runner execution.
---

# Test Plan Generation

Use this skill for prose-first generation in `codex-qa-agent`.

## Purpose

Create a `tools.generation.domain.models.NormalizedTestPlan` from operator prose. Stop at planned test cases. Do not render runnable markdown scenarios and do not execute `scenario_runner`.

## Accepted Inputs

- Inline prose in `GenerationSourceInput.content`
- File-backed prose in `GenerationSourceInput.source_path`
- Required fields: `source_id`, `project`, and either `content` or `source_path`
- Default input format: `SourceInputFormat.PROSE`

Structured input is reserved for future work. If `input_format=structured`, report it as unsupported for this phase.

## Workflow

1. Build a typed `GenerationSourceInput`.
2. Build `GenerateTestPlanRequest(source_input=..., workspace_root=<repo-root>)`.
3. Run `GenerateTestPlanUseCase().execute(request)`.
4. Read the returned `GenerationRunResult`.
5. Inspect diagnostics before trusting the plan.
6. Use `normalized_plan` as the canonical output.
7. Reference artifact paths from `artifact_paths` when reporting.

`GenerationPipelineService` exists only as a compatibility facade. Prefer the use-case boundary for new skill-facing work.

Optional code facts collection is available through `GenerateTestPlanOptions(collect_code_facts=True)`
plus an explicit `project_path` and `CodeFactsScope`. It returns a `GenerationEvidenceBundle` beside the
plan.

Optional evidence enrichment is available through `GenerateTestPlanOptions(collect_code_facts=True,
enrichment_enabled=True)`. It returns an `EnrichedTestPlanResult`, updates the returned
`normalized_plan` with conservative evidence hints, and appends evidence traceability links. It still
stops before markdown scenario rendering.

## Outputs

The flow returns:

- `GenerationRunResult`
- `NormalizedTestPlan`
- `PlannedTestCase[]`
- `GenerationDiagnostic[]`
- `TraceabilityMap`
- optional `GenerationEvidenceBundle`
- optional `EnrichedTestPlanResult`

Each planned case may include title, objective, preconditions, prose-level steps, expected results, priority, assumptions, open questions, tags, and source refs.

## Artifacts

Generation artifacts are isolated from runner artifacts:

```text
.codex-qa/generation/runs/<run_id>/
  context.json
  evidence.json        # only when code facts collection is enabled
  summary.json

artifacts/agent/generation/<source_slug>-<run_id>/
  manifest.json
  context.json
  source-input.json
  normalized-source.json
  normalized-plan.json
  traceability-map.json
  diagnostics.json
  evidence-bundle.json # only when code facts collection is enabled
  enriched-plan.json   # only when evidence enrichment is enabled
  enrichment-result.json
  applied-evidence.json
  unapplied-evidence.json
  summary.json
```

## Status And Diagnostics

- Treat missing/empty source, missing source file, unreadable source file, unsupported source format, and no detected test cases as `BLOCKED`.
- Treat ambiguous prose, inferred assumptions, incomplete testable detail, and current-phase unsupported constructs as diagnostics.
- Preserve ambiguity in `open_questions` or diagnostics instead of inventing endpoints, payloads, DB tables, auth flows, or exact scenario steps.

## Must Not Do

- Do not perform dynamic code scanning as part of normalization.
- Do not collect code facts without explicit scoped paths.
- Do not use code facts to mutate `NormalizedTestPlan` unless `enrichment_enabled=True`.
- Do not treat evidence hints as runnable scenario steps.
- Do not call LLMs or external APIs.
- Do not render markdown scenarios.
- Do not run or modify `scenario_runner`.
- Do not add pause/resume or guided/manual behavior for generation.
- Do not store canonical planning fields only in `metadata`.

## Reporting

Report:

- target project
- source input origin
- final status
- number of planned test cases
- diagnostics, assumptions, and open questions
- artifact paths

State clearly that this is deterministic rule-based prose normalization, not LLM-backed understanding.
