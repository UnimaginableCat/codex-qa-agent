# Downstream Modes

## Purpose

These phases come after plan authoring/generation. They are optional and should not be confused
with the primary job of this skill, which is to produce a good `NormalizedTestPlan`.

Supported downstream phases:

- `render`
- `promote`
- `validate`

## Render

Use render when the user wants markdown draft scenarios or previews.

Command:

```powershell
<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root . `
  --render-drafts
```

Rendering is conservative:

- single-endpoint API cases need authored `planned_route`
- workflow cases need complete `workflow_steps[]`
- missing route or incomplete workflow data produces deferred items, not invented drafts

## Review And Promotion

Review:

```powershell
<venv-python> -m tools.generation.cli `
  --review-drafts `
  --run-id <generation-run-id> `
  --workspace-root .
```

Promote one:

```powershell
<venv-python> -m tools.generation.cli `
  --promote-draft `
  --run-id <generation-run-id> `
  --draft-id draft-tc-001 `
  --workspace-root . `
  --target-dir scenarios/generated
```

Promote all:

```powershell
<venv-python> -m tools.generation.cli `
  --promote-all-drafts `
  --run-id <generation-run-id> `
  --workspace-root . `
  --target-dir scenarios/generated
```

## Validate

Parser-only:

```powershell
<venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/example.md `
  --output-format text
```

Compile-only:

```powershell
<venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/example.md `
  --mode compile `
  --output-format text
```

Preflight-only:

```powershell
<venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/example.md `
  --mode preflight `
  --workspace-root . `
  --output-format text
```
