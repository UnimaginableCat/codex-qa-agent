# Pipeline Commands

Use these commands through the workspace-root venv interpreter. Do not use target project venvs under `code/<project>` for workspace generation, runner, API, or DB tools.

## Authoring Handoff

For a managed staged bundle, the authoring branch must end with:

```powershell
<venv-python> -m tools.generation.cli `
  --validate-authoring-bundle `
  --path artifacts/agent/generation/<run_id> `
  --output-format text
```

Do not compile before this passes.

## Compile And Generate

```powershell
<venv-python> -m tools.generation.cli `
  --compile-authoring-plan `
  --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml `
  --output artifacts/agent/generation `
  --output-format text

<venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --output-format text

<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root . `
  --output-format text
```

## Render, Review, Promote

```powershell
<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root . `
  --render-drafts `
  --output-format text

<venv-python> -m tools.generation.cli `
  --review-drafts `
  --run-id <generation-run-id> `
  --workspace-root . `
  --output-format text

<venv-python> -m tools.generation.cli `
  --promote-all-drafts `
  --run-id <generation-run-id> `
  --workspace-root . `
  --target-dir scenarios/generated `
  --output-format text
```

Use `--purge-target-dir` only when the user explicitly wants a rerender/re-promote cycle that replaces the previous generated directory.

## Validate Promoted Scenarios

```powershell
<venv-python> -m tools.generation.cli `
  --validate-scenario-dir `
  --path scenarios/generated/<source>-<run_id> `
  --mode compile `
  --output-format text
```

Use `--mode preflight` only when environment-aware readiness is requested or needed before execution.

## Execute Promoted Scenarios

Guided batch execution is the default:

```powershell
<venv-python> -m tools.scenario_runner.batch_cli `
  --scenario-dir scenarios/generated/<source>-<run_id>
```

Auto mode only when requested:

```powershell
<venv-python> -m tools.scenario_runner.batch_cli `
  --scenario-dir scenarios/generated/<source>-<run_id> `
  --mode auto
```

If guided batch execution pauses, inspect `operator_state` and stop for the operator action. Resume with:

```powershell
<venv-python> -m tools.scenario_runner.cli `
  --resume <pause-state.json> `
  --action <action_id>
```

## Artifact Map

Generation bundle:

- `artifacts/agent/generation/<run_id>/summary.json`
- `artifacts/agent/generation/<run_id>/diagnostics.json`
- `artifacts/agent/generation/<run_id>/normalized-plan.json`
- `artifacts/agent/generation/<run_id>/scenario-render-result.json`
- `artifacts/agent/generation/<run_id>/promotion-result.json`

Promoted scenarios:

- `scenarios/generated/<source>-<run_id>/`

Runner outputs:

- `artifacts/agent/scenario-batches/<batch-id>/summary.json`
- `artifacts/agent/scenario-batches/<batch-id>/report.md`
- `.codex-qa/runs/<run-id>/summary.json`
- `artifacts/agent/scenario-runs/<run-id>/report.md`
