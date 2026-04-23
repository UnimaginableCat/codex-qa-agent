---
name: test-plan-generation
description: Generate a typed NormalizedTestPlan in the local codex-qa-agent workspace. Prefer agent-authored structured plan input when the agent can decompose the request; use prose input only as fallback/bootstrap. Use when the desired output is PlannedTestCase items plus diagnostics/artifacts rather than scenario_runner execution.
---

# Test Plan Generation

Use this skill for deterministic test-plan generation in `codex-qa-agent`.

## Purpose

Create a `tools.generation.domain.models.NormalizedTestPlan`. The preferred first input is an
agent-authored structured draft (`AgentTestPlanInput`) because broad operator prose often needs
semantic decomposition before it becomes useful. Prose input remains available as fallback/bootstrap.

Optional downstream stages can collect scoped code facts, enrich the plan, render non-executed
markdown draft previews, review/promote drafts, and validate edited scenarios. Do not execute
`scenario_runner` from this skill.

## Accepted Inputs

- Preferred: `--agent-plan-file <path>` containing `AgentTestPlanInput` JSON.
- Use-case API: `GenerateTestPlanRequest(input_mode=agent_plan, agent_plan=AgentTestPlanInput(...))`.
- Fallback: inline prose via `--prose` or file-backed prose via `--source-file`.
- For `agent_plan`, required fields are `source_id`, `project`, `title`, and `planned_test_cases[]`.
- For prose fallback, required fields are `source_id`, `project`, and either inline content or source file.

`NormalizedTestPlan` remains the canonical internal plan contract for every input mode.

## Agent Plan Contract

Minimum JSON shape:

```json
{
  "source_id": "internal-user-sessions",
  "project": "code/demo",
  "title": "Internal user sessions",
  "goal": "Cover session lifecycle behavior.",
  "assumptions": [],
  "open_questions": [],
  "planned_test_cases": [
    {
      "title": "Authenticate session",
      "objective": "Verify session authentication.",
      "kind": "api",
      "preconditions": [],
      "actions": ["Call the authenticate session API."],
      "expected_outcomes": ["A session token is returned."],
      "priority": "high",
      "tags": ["session"],
      "unresolved_items": ["Auth fixture is not selected yet."]
    }
  ]
}
```

Do not use loose dict-only glue as the canonical contract. The local service reads this through
`AgentTestPlanInput` and `AgentPlannedTestCaseInput`.

## Compact Request Format

Use this operator-facing format when the user wants a short prompt:

```text
Use skill: test-plan-generation

mode: <plan-only | plan-with-evidence | draft-preview | review-drafts | promote-draft | validate-scenario>
input_mode: <agent_plan | prose>
validation_mode: <parser | compile | preflight>
agent_plan_file: <path to AgentTestPlanInput JSON>
project: code/<project-name>
source_id: <source id for prose fallback>
prose: <fallback source text>
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

Default interpretation:

- Prefer `input_mode=agent_plan` when the agent can decompose the operator request into cases.
- Use prose only when the operator explicitly wants bootstrap from prose or no decomposition is available.
- If `agent_plan_file` is supplied, CLI defaults to `input_mode=agent_plan`.
- If `--prose` or `--source-file` is supplied, CLI defaults to `input_mode=prose`.
- Evidence modes require explicit `project_path` and `scope`; never infer repository-wide scope.
- If a required field is missing, ask only for that field.

## Interpreter Rule

Before running any generation CLI command, resolve the target project venv/interpreter and prefer it.

Priority:

1. target project venv/interpreter
2. workspace-level Python known to satisfy repo requirements
3. fallback `py -3.14` only when no better project-specific interpreter is available

## Modes

### Mode A - Plan Only

Preferred structured input:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/input/internal-user-sessions-plan.json `
  --workspace-root .
```

Fallback prose:

```powershell
<project-venv-python> -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user and get user by id" `
  --workspace-root .
```

### Mode B - Plan With Evidence

Use only with explicit project path and explicit scoped files/directories:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/input/users-api-plan.json `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --evidence-scope-path app/api/users.py
```

Code facts are extracted only from `CodeFactsScope.paths`. Stack selection is deterministic:

- explicit `stack_hint`, when it matches the explicit scope files
- `.py` scope -> Python extractor
- `.java` scope with Spring mapping annotations -> Java/Spring extractor

Unsupported, mixed, or ambiguous scopes produce diagnostics instead of broad scanning.

### Mode C - Draft Scenario Preview

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/input/users-api-plan.json `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --render-drafts `
  --evidence-scope-path app/api/users.py
```

Drafts are non-executed preview artifacts. They are parser-validated only.

### Mode D - Review And Promote Drafts

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

Promotion never overwrites existing files and never executes scenarios.

### Mode E - Manual Patch Revalidation

Parser:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/users-draft-tc-001.md `
  --output-format text
```

Compile-only:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/users-draft-tc-001.md `
  --mode compile `
  --output-format text
```

Preflight-only:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/users-draft-tc-001.md `
  --mode preflight `
  --workspace-root . `
  --output-format text
```

All validation modes are non-executing.

## Workflow

1. Resolve the target project venv/interpreter first.
2. If the agent can decompose the request, author an `AgentTestPlanInput` JSON and use `--agent-plan-file`.
3. Use prose fallback only when structured decomposition is not available yet.
4. Add evidence only with explicit `project_path` and `scope`.
5. Read the adapter JSON summary.
6. Inspect diagnostics before trusting the plan.
7. Treat `normalized-plan.json` as the canonical generated plan artifact.
8. Promote only operator-selected drafts.
9. Revalidate manually edited drafts/scenarios before considering execution.

`GenerateTestPlanUseCase` is the canonical application entrypoint. The CLI only gathers arguments
and constructs typed request objects.

## Outputs

- `GenerationRunResult`
- `NormalizedTestPlan`
- `PlannedTestCase[]`
- `GenerationDiagnostic[]`
- `TraceabilityMap`
- optional `GenerationEvidenceBundle`
- optional `EnrichedTestPlanResult`
- optional `ScenarioRenderResult`

## Artifacts

Generation artifacts remain isolated from runner artifacts:

```text
.codex-qa/generation/runs/<run_id>/
  context.json
  evidence.json
  summary.json

artifacts/agent/generation/<source_slug>-<run_id>/
  manifest.json
  source-input.json
  normalized-source.json
  normalized-plan.json
  traceability-map.json
  diagnostics.json
  evidence-bundle.json
  enriched-plan.json
  scenario-drafts/
  scenario-render-result.json
  promotion-result.json
  summary.json
```

## Diagnostics

Treat missing/empty prose source, missing source file, unreadable source file, unsupported source
format, invalid agent plan fields, and no detected/declared test cases as blocking. Preserve
ambiguity in unresolved items, open questions, or diagnostics instead of inventing endpoints,
payloads, DB tables, auth flows, or exact runtime steps.

## Must Not Do

- Do not run or modify `scenario_runner`.
- Do not force broad operator requests through prose scanning when the agent can author a structured plan.
- Do not collect code facts without explicit scoped paths.
- Do not infer `project_path`, `CodeFactsScope`, or `stack_hint` from vague prose alone.
- Do not perform repository-wide discovery.
- Do not call LLMs or external APIs from local generation services.
- Do not treat generated draft markdown as executable or reviewed scenarios.
- Do not auto-promote drafts or overwrite existing scenario files.
- Do not execute scenarios during validation.
- Do not add pause/resume or guided/manual behavior for generation.
- Do not store canonical planning fields only in `metadata`.

## Reporting

Report target project, input mode, source input origin, final status, planned case count,
diagnostics/assumptions/open questions, and artifact paths. State clearly whether the result came
from agent-authored structured input or fallback prose normalization.
