# Generation Pipeline Foundation

Phase 1 generation artifacts are isolated from `scenario_runner` artifacts.

Canonical request bundle:

```text
artifacts/agent/generation/<run_id>/
  manifest.json
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

Primary flow:

```text
agent-authored plan input -> GenerateTestPlanUseCase -> NormalizedTestPlan
```

Prose remains a fallback/bootstrap path:

```text
prose -> prose normalizer -> NormalizedTestPlan
```

For true end-to-end coverage inside one case, use `workflow_steps[]` on
`AgentPlannedTestCaseInput`. If that workflow includes successful state-changing API operations,
add persisted-state verification with case-level `db_verification` or a `db` workflow step.

Authoring helper workflow:

```text
agent reasoning
-> scaffold AgentTestPlanInput
-> validate AgentTestPlanInput
-> run generation
```

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

CLI validate-only:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --output-format text
```

Structured generation:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root .
```

Fallback prose generation:

```powershell
<project-venv-python> -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user" `
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
```

Promotion is explicit, never overwrites existing files, and writes `promotion-result.json` under the
generation artifact bundle. When using the default `scenarios/generated` root, promoted drafts are
written under a run-scoped subdirectory such as `scenarios/generated/<source>-<run_id>/`.
