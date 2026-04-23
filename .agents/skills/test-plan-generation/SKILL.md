---
name: test-plan-generation
description: Generate a typed NormalizedTestPlan from human-readable prose in the local codex-qa-agent workspace. Use when the user asks to create, normalize, plan, or generate a test plan from a feature/test request description, and the desired output is PlannedTestCase items plus diagnostics/artifacts rather than runnable markdown scenarios or scenario_runner execution.
---

# Test Plan Generation

Use this skill for prose-first generation in `codex-qa-agent`.

## Purpose

Create a `tools.generation.domain.models.NormalizedTestPlan` from operator prose. Optionally render
non-executed markdown draft previews from evidence-supported cases. Promote drafts into `scenarios/`
only when the operator explicitly selects a draft id. Do not execute `scenario_runner`.

## Accepted Inputs

- Inline prose in `GenerationSourceInput.content`
- File-backed prose in `GenerationSourceInput.source_path`
- Required fields: `source_id`, `project`, and either `content` or `source_path`
- Default input format: `SourceInputFormat.PROSE`

Structured input is reserved for future work. If `input_format=structured`, report it as unsupported for this phase.

## Short Request Format

Use this compact operator-facing format by default. The agent should expand it into the correct CLI
or use-case invocation without asking for the long operational prompt again.

```text
Use skill: test-plan-generation

mode: <plan-only | plan-with-evidence | draft-preview | review-drafts | promote-draft>
project: code/<project-name>
source_id: <optional for review/promote>
prose: <required for generation modes>
project_path: <required for evidence modes>
scope:
- <explicit file or directory path>
run_id: <required for review/promote>
draft_id: <required for promote-draft>
target_dir: scenarios/<optional-subdir>
allow_invalid: true|false
```

### Field Mapping

- `mode`
  - `plan-only` -> prose to `NormalizedTestPlan`
  - `plan-with-evidence` -> prose + explicit scope + enrichment
  - `draft-preview` -> enriched plan + parser-validated draft markdown preview
  - `review-drafts` -> inspect already generated drafts by `run_id`
  - `promote-draft` -> copy one selected draft into `scenarios/`
- `project`
  - required for generation modes
- `source_id`
  - required for generation modes
- `prose`
  - required for `plan-only`, `plan-with-evidence`, `draft-preview`
- `project_path`
  - required for `plan-with-evidence` and `draft-preview`
- `scope`
  - required for `plan-with-evidence` and `draft-preview`
  - each item maps to `--evidence-scope-path`
- `run_id`
  - required for `review-drafts` and `promote-draft`
- `draft_id`
  - required for `promote-draft`
- `target_dir`
  - optional for `promote-draft`, defaults to `scenarios/generated`
- `allow_invalid`
  - optional for `promote-draft`, defaults to `false`

### Default Agent Interpretation

- If the request uses this short format, do not ask the operator to restate it in longer prose.
- If `mode=plan-with-evidence` or `mode=draft-preview`, require explicit `project_path` and `scope`.
- Never infer repository-wide scope from `project` alone.
- If a required field for the selected mode is missing, ask only for the missing field.

## Modes

### Mode A - Plan Only

Use when the operator provides prose and does not provide an explicit code evidence scope.

```powershell
py -3.14 -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user and get user by id" `
  --workspace-root .
```

This mode produces a prose-first `NormalizedTestPlan`. It does not collect code facts and does not
enrich cases with evidence.

### Mode B - Plan With Evidence

Use only when the operator provides an explicit target project path and explicit scoped files or
directories to inspect.

```powershell
py -3.14 -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user" `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --evidence-scope-path app/api/users.py
```

This mode invokes `GenerateTestPlanUseCase` with `collect_code_facts=True` and
`enrichment_enabled=True`. Code facts are extracted only from `CodeFactsScope.paths`; there is no
implicit repository-wide discovery.

### Mode C - Draft Scenario Preview

Use only after Mode B inputs are available and the operator wants markdown preview artifacts.

```powershell
py -3.14 -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user" `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --render-drafts `
  --evidence-scope-path app/api/users.py
```

This mode renders non-executed scenario draft artifacts only for cases that have endpoint path and
HTTP method evidence hints. Drafts are parser-validated with `MarkdownScenarioParser.parse_result()`.
No compile, preflight, runtime execution, API workflow, or DB workflow is triggered.

### Mode D - Review And Promote Drafts

Use after Mode C has produced draft artifacts.

Review:

```powershell
py -3.14 -m tools.generation.cli `
  --review-drafts `
  --run-id <generation-run-id> `
  --workspace-root .
```

Promote one explicit draft:

```powershell
py -3.14 -m tools.generation.cli `
  --promote-draft `
  --run-id <generation-run-id> `
  --draft-id draft-tc-001 `
  --workspace-root . `
  --target-dir scenarios/generated
```

Promotion copies the selected draft to `scenarios/` with a metadata header. It never overwrites
existing files. Invalid drafts are rejected unless the operator explicitly passes `--allow-invalid`.
Promotion still does not execute the scenario.

## Canonical Short Examples

Plan only:

```text
Use skill: test-plan-generation

mode: plan-only
project: code/demo
source_id: users-api
prose: Проверить создание пользователя и получение по id
```

Plan with evidence:

```text
Use skill: test-plan-generation

mode: plan-with-evidence
project: code/demo
source_id: users-api
project_path: code/demo
scope:
- app/api/users.py
prose: Проверить создание пользователя и получение по id
```

Draft preview:

```text
Use skill: test-plan-generation

mode: draft-preview
project: code/demo
source_id: users-api
project_path: code/demo
scope:
- app/api/users.py
prose: Проверить создание пользователя
```

Review drafts:

```text
Use skill: test-plan-generation

mode: review-drafts
run_id: <generation-run-id>
```

Promote draft:

```text
Use skill: test-plan-generation

mode: promote-draft
run_id: <generation-run-id>
draft_id: draft-tc-001
target_dir: scenarios/generated
```

## Workflow

1. Choose Mode A or Mode B.
2. Prefer `python -m tools.generation.cli` / `py -3.14 -m tools.generation.cli` for agent-facing runs.
3. Read the JSON summary printed by the adapter.
4. Inspect diagnostics before trusting the plan.
5. Use `normalized_plan` artifacts as the canonical output.
6. Reference artifact paths from `artifact_paths` when reporting.
7. For draft review, surface parse status and diagnostics before promotion.
8. Promote only the operator-selected `draft_id`.

`GenerationPipelineService` exists only as a compatibility facade. Prefer the use-case boundary for new skill-facing work.

Optional code facts collection is available through `GenerateTestPlanOptions(collect_code_facts=True)`
plus an explicit `project_path` and `CodeFactsScope`. It returns a `GenerationEvidenceBundle` beside the
plan.

Optional evidence enrichment is available through `GenerateTestPlanOptions(collect_code_facts=True,
enrichment_enabled=True)`. It returns an `EnrichedTestPlanResult`, updates the returned
`normalized_plan` with conservative evidence hints, and appends evidence traceability links.

Optional draft rendering is available through `GenerateTestPlanOptions(render_scenario_drafts=True)`
or CLI `--render-drafts`. It writes preview artifacts and validates them with the parser only.

Draft review and promotion are available through CLI `--review-drafts` and `--promote-draft`.

The CLI adapter is only an argument-gathering layer. It must not be treated as the source of
generation semantics.

## Outputs

The flow returns:

- `GenerationRunResult`
- `NormalizedTestPlan`
- `PlannedTestCase[]`
- `GenerationDiagnostic[]`
- `TraceabilityMap`
- optional `GenerationEvidenceBundle`
- optional `EnrichedTestPlanResult`
- optional `ScenarioRenderResult`

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
  scenario-drafts/
    <draft>.md
  scenario-render-result.json
  scenario-parse-results.json
  unsupported-checks.json
  deferred-items.json
  promotion-result.json
  summary.json
```

## Status And Diagnostics

- Treat missing/empty source, missing source file, unreadable source file, unsupported source format, and no detected test cases as `BLOCKED`.
- Treat ambiguous prose, inferred assumptions, incomplete testable detail, and current-phase unsupported constructs as diagnostics.
- Preserve ambiguity in `open_questions` or diagnostics instead of inventing endpoints, payloads, DB tables, auth flows, or exact scenario steps.

## Must Not Do

- Do not perform dynamic code scanning as part of normalization.
- Do not collect code facts without explicit scoped paths.
- Do not infer `project_path` or `CodeFactsScope` from the whole repository.
- Do not run Mode B unless the operator supplied a targeted evidence scope.
- Do not use code facts to mutate `NormalizedTestPlan` unless `enrichment_enabled=True`.
- Do not treat evidence hints as runnable scenario steps.
- Do not call LLMs or external APIs.
- Do not treat generated draft markdown as executable or reviewed scenarios.
- Do not copy draft markdown into `scenarios/` unless the operator explicitly selects a `draft_id`.
- Do not overwrite existing scenario files during promotion.
- Do not auto-promote drafts.
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
