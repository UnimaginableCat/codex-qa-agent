# Generation Pipeline Foundation

Phase 1 generation artifacts are isolated from `scenario_runner` artifacts.

Canonical request bundle:

```text
artifacts/agent/generation/<run_id>/
  manifest.json
  authoring-plan.yaml
  agent-plan.json
  context.json
  source-input.json
  normalized-source.json
  normalized-plan.json
  traceability-map.json
  diagnostics.json
  scenario-drafts/
    <draft>.md
  scenario-render-result.json
  scenario-parse-results.json
  unsupported-checks.json
  deferred-items.json
  promotion-result.json
  summary.json
```

Treat this bundle as the single source of truth for one generation request.

Skill routing:

```text
broad workspace request -> qa-entrypoint
coverage decomposition / authoring DSL -> agent-plan-authoring
compile / generate / render / review / promote / validate -> test-plan-generation
```

Preferred DSL flow:

```text
authoring-plan.yaml
-> compiler
-> agent-plan.json
-> GenerateTestPlanUseCase
-> NormalizedTestPlan
```

When scaffolded through the CLI, `authoring-plan.yaml` lives inside the generation run bundle at
`artifacts/agent/generation/<run_id>/authoring-plan.yaml`.

`defaults.actor` in `authoring-plan.yaml` is not just descriptive metadata. It compiles into a
rendered scenario variable `actor = literal:<value>` and acts as an execution profile selector for
actor-scoped API/DB env keys such as `API_BASE_URL__API_CLIENT` or `DATABASE_URL__API_CLIENT`.

`entities.<entity>.id_field` is now executable authoring contract too. It names the canonical entity
identity variable used across setup chains and persisted-state templates, for example `user_id`.

Prose remains a fallback/bootstrap path:

```text
prose -> prose normalizer -> NormalizedTestPlan
```

For true end-to-end coverage inside one case, use `workflow_steps[]` on
`AgentPlannedTestCaseInput`. If that workflow includes successful state-changing API operations,
add persisted-state verification with case-level `db_verification` or a `db` workflow step.

Authoring helper workflow:

```text
qa-entrypoint
-> agent-plan-authoring
-> author or refine authoring-plan.yaml
-> test-plan-generation
-> validate / compile / generate
```

Preferred CLI flow

Authoring-plan scaffold:

```powershell
<project-venv-python> -m tools.generation.cli `
  --init-authoring-plan `
  --output artifacts/agent/generation `
  --source-id users-api `
  --project code/demo `
  --name "Users API" `
  --goal "Cover user API behavior."
```

Authoring-plan validate-only:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-authoring-plan `
  --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml `
  --output-format text
```

Authoring-plan compile:

```powershell
<project-venv-python> -m tools.generation.cli `
  --compile-authoring-plan `
  --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml `
  --output artifacts/agent/generation `
  --output-format text
```

Direct generation from authoring-plan:

```powershell
<project-venv-python> -m tools.generation.cli `
  --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml `
  --workspace-root .
```

Compiled bundle flow

Validate compiled bundle:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --output-format text
```

Generate from compiled bundle:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root .
```

Draft scenario rendering preview:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root . `
  --render-drafts
```

Rendering is conservative: it emits parser-validated markdown previews only for cases with authored
route details (`planned_route`) or complete `workflow_steps[]`. Unsupported cases are written to
deferred/unsupported artifacts. No scenario execution, compile, preflight, API workflow, or DB
workflow is triggered.

When rendered drafts include `actor = literal:<value>`, downstream execution uses that value to
select actor-scoped env profiles before falling back to base `API_*` or `DATABASE_*` keys.

Review and promotion:

```powershell
<project-venv-python> -m tools.generation.cli `
  --review-drafts `
  --run-id <generation-run-id> `
  --workspace-root .

<project-venv-python> -m tools.generation.cli `
  --promote-draft `
  --run-id <generation-run-id> `
  --draft-id draft-tc-001 `
  --workspace-root . `
  --target-dir scenarios/generated

<project-venv-python> -m tools.generation.cli `
  --promote-all-drafts `
  --run-id <generation-run-id> `
  --workspace-root . `
  --target-dir scenarios/generated

<project-venv-python> -m tools.generation.cli `
  --promote-all-drafts `
  --run-id <generation-run-id> `
  --workspace-root . `
  --target-dir scenarios/generated `
  --purge-target-dir

<project-venv-python> -m tools.generation.cli `
  --validate-scenario-dir `
  --path scenarios/generated/<source>-<run_id> `
  --mode compile `
  --output-format text
```

Promotion is explicit, never overwrites existing files, and writes `promotion-result.json` under the
generation artifact bundle. When using the default `scenarios/generated` root, promoted drafts are
written under a run-scoped subdirectory such as `scenarios/generated/<source>-<run_id>/`. Use
`--purge-target-dir` only for deliberate rerender/re-promote cycles when the resolved target directory
should be deleted before writing the refreshed scenario set.

Use `--validate-scenario-dir --mode compile` as the normal post-promotion gate when you want one
summary verdict for a whole promoted scenario directory without writing shell loops.

Low-level escape hatches

Use these only for manual repair, debugging, or explicit direct control. They are not the default
skill-routed path.

CLI scaffold:

```powershell
<project-venv-python> -m tools.generation.cli `
  --init-agent-plan `
  --output artifacts/agent/generation `
  --source-id users-api `
  --project code/demo `
  --name "Users API" `
  --goal "Cover user API behavior."
```

Fallback prose generation:

```powershell
<project-venv-python> -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user" `
  --workspace-root .
```
