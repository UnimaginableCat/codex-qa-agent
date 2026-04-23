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

mode: <plan-only | plan-with-evidence | draft-preview | review-drafts | promote-draft | validate-scenario>
validation_mode: <parser | compile | preflight>
project: code/<project-name>
source_id: <optional for review/promote>
prose: <required for generation modes>
project_path: <required for evidence modes>
scope:
- <explicit file or directory path>
stack_hint: <optional python | java_spring>
run_id: <required for review/promote>
draft_id: <required for promote-draft>
target_dir: scenarios/<optional-subdir>
allow_invalid: true|false
path: <required for validate-scenario>
```

### Field Mapping

- `mode`
  - `plan-only` -> prose to `NormalizedTestPlan`
  - `plan-with-evidence` -> prose + explicit scope + enrichment
  - `draft-preview` -> enriched plan + parser-validated draft markdown preview
  - `review-drafts` -> inspect already generated drafts by `run_id`
  - `promote-draft` -> copy one selected draft into `scenarios/`
  - `validate-scenario` -> revalidate one manually edited draft/promoted scenario file with parser mode or compile-only mode
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
- `stack_hint`
  - optional for `plan-with-evidence` and `draft-preview`
  - pass through only when the target stack is already known
- `draft_id`
  - required for `promote-draft`
- `target_dir`
  - optional for `promote-draft`, defaults to `scenarios/generated`
- `allow_invalid`
  - optional for `promote-draft`, defaults to `false`
- `path`
  - required for `validate-scenario`
- `validation_mode`
  - optional for `validate-scenario`, defaults to `parser`
  - `parser` runs markdown parser checks only
  - `compile` runs parser checks plus scenario compiler contract checks, still without execution
  - `preflight` runs parser, compile, then existing scenario_runner preflight checks, still without execution

### Default Agent Interpretation

- If the request uses this short format, do not ask the operator to restate it in longer prose.
- If `mode=plan-with-evidence` or `mode=draft-preview`, require explicit `project_path` and `scope`.
- If `stack_hint` is provided, pass it through as an explicit extractor selection hint.
- Never infer repository-wide scope from `project` alone.
- If a required field for the selected mode is missing, ask only for the missing field.

## Interpreter Rule

Before running any generation CLI command, resolve the Python interpreter/venv for the target
project and prefer that interpreter first.

Priority:

1. target project venv/interpreter resolved from the project workspace
2. workspace-level Python explicitly known to satisfy the repo requirements
3. fallback `py -3.14` only when no better project-specific interpreter is available

This matters even for deterministic generation because local imports, parser behavior, and helper
tooling must run under the same interpreter family the project expects. Do not default straight to
global Python if a project venv is available.

## Modes

### Mode A - Plan Only

Use when the operator provides prose and does not provide an explicit code evidence scope.

```powershell
<project-venv-python> -m tools.generation.cli `
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
<project-venv-python> -m tools.generation.cli `
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
implicit repository-wide discovery. Stack selection is deterministic:

- explicit `stack_hint`, when it matches the explicit scope files
- otherwise `.py` scope -> Python extractor
- otherwise `.java` scope with Spring controller annotations -> Java/Spring extractor

If scope is mixed, unsupported, or not applicable to a supported extractor, surface diagnostics
instead of forcing extraction.

### Mode C - Draft Scenario Preview

Use only after Mode B inputs are available and the operator wants markdown preview artifacts.

```powershell
<project-venv-python> -m tools.generation.cli `
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
<project-venv-python> -m tools.generation.cli `
  --review-drafts `
  --run-id <generation-run-id> `
  --workspace-root .
```

Promote one explicit draft:

```powershell
<project-venv-python> -m tools.generation.cli `
  --promote-draft `
  --run-id <generation-run-id> `
  --draft-id draft-tc-001 `
  --workspace-root . `
  --target-dir scenarios/generated
```

Promotion copies the selected draft to `scenarios/` with a metadata header. It never overwrites
existing files. Invalid drafts are rejected unless the operator explicitly passes `--allow-invalid`.
Promotion still does not execute the scenario.

### Mode E - Manual Patch Revalidation

Use after the operator manually edits a draft or promoted scenario file and wants parser-only or
compile-only feedback before any execution.

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/users-draft-tc-001.md `
  --output-format text
```

This mode loads the markdown file, runs `MarkdownScenarioParser.parse_result()`, rebuilds the
checklist/edit-target/template guidance, and returns a promotion advisory. It does not need
generation artifacts and does not execute the scenario.

Compile-only readiness:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/users-draft-tc-001.md `
  --mode compile `
  --output-format text
```

Compile mode additionally calls the existing `ScenarioCompiler` to check variable dependencies,
capture contracts, step references, and supported expectation DSL. It must not run preflight,
API tools, DB tools, or `ScenarioRunnerService`.

Preflight-only workspace readiness:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/users-draft-tc-001.md `
  --mode preflight `
  --workspace-root . `
  --output-format text
```

Preflight mode additionally calls the existing `ScenarioPreflightChecker` after parser and compile
validation pass. It checks workspace/environment readiness such as project path, env file, external
inputs, local dependencies, tool entrypoints, and output directories. It must not execute scenario
steps or call API/DB workflows.

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

Java/Spring evidence:

```text
Use skill: test-plan-generation

mode: plan-with-evidence
project: code/demo
source_id: users-java
project_path: code/demo
stack_hint: java_spring
scope:
- src/main/java/demo/UserController.java
prose: Проверить получение пользователя по id
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

Validate manually edited scenario:

```text
Use skill: test-plan-generation

mode: validate-scenario
path: scenarios/generated/users-draft-tc-001.md
validation_mode: compile
```

## Workflow

1. Choose Mode A or Mode B.
2. Resolve the target project venv/interpreter first.
3. Prefer `<project-venv-python> -m tools.generation.cli` for agent-facing runs.
4. Use `py -3.14 -m tools.generation.cli` only as fallback when project venv is unavailable.
5. Read the JSON summary printed by the adapter.
6. Inspect diagnostics before trusting the plan.
7. Use `normalized_plan` artifacts as the canonical output.
8. Reference artifact paths from `artifact_paths` when reporting.
9. For draft review, surface parse status and diagnostics before promotion.
10. Promote only the operator-selected `draft_id`.
11. After manual edits, use `validate-scenario` for parser-only or compile-only feedback before considering execution.

`GenerationPipelineService` exists only as a compatibility facade. Prefer the use-case boundary for new skill-facing work.

Optional code facts collection is available through `GenerateTestPlanOptions(collect_code_facts=True)`
plus an explicit `project_path` and `CodeFactsScope`. It returns a `GenerationEvidenceBundle` beside the
plan. Extractor resolution is handled by `CodeFactsExtractionService`; the skill must not decide stack
semantics itself beyond passing an explicit `stack_hint` when the operator already knows the target stack.

Optional evidence enrichment is available through `GenerateTestPlanOptions(collect_code_facts=True,
enrichment_enabled=True)`. It returns an `EnrichedTestPlanResult`, updates the returned
`normalized_plan` with conservative evidence hints, and appends evidence traceability links.

Optional draft rendering is available through `GenerateTestPlanOptions(render_scenario_drafts=True)`
or CLI `--render-drafts`. It writes preview artifacts and validates them with the parser only.

Draft review and promotion are available through CLI `--review-drafts` and `--promote-draft`.
Manual patch revalidation is available through CLI `--validate-scenario --path <scenario.md>`.
Use `--mode compile` when the operator asks whether the scenario is structurally runner-ready.
Use `--mode preflight` when the operator asks whether the current workspace/environment is ready
to execute the parser/compile-valid scenario.

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
- Do not infer `stack_hint` from vague prose alone.
- Do not run Mode B unless the operator supplied a targeted evidence scope.
- Do not skip project venv/interpreter resolution when the target project has its own environment.
- Do not use code facts to mutate `NormalizedTestPlan` unless `enrichment_enabled=True`.
- Do not treat evidence hints as runnable scenario steps.
- Do not call LLMs or external APIs.
- Do not treat generated draft markdown as executable or reviewed scenarios.
- Do not copy draft markdown into `scenarios/` unless the operator explicitly selects a `draft_id`.
- Do not overwrite existing scenario files during promotion.
- Do not auto-promote drafts.
- Do not run or modify `scenario_runner`.
- Do not execute scenarios during `validate-scenario`; parser-only or compile-only validation is the limit.
- Do not treat compile-only readiness as runtime correctness; it only checks pre-execution contracts.
- Do not treat preflight readiness as runtime correctness; it checks environment/workspace readiness before execution.
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
