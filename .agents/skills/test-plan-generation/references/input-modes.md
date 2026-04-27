# Input Modes

## Primary Rule

Use `authoring_plan` when authored DSL already exists or the upstream skill just produced
`authoring-plan.yaml`.

Use `agent_plan` only as a low-level fallback when you are debugging, repairing, or intentionally
driving generation from a compiled bundle.

Use prose only when:

- the request is too vague to decompose responsibly yet
- the user explicitly wants a prose bootstrap
- structured authoring would add unnecessary overhead

## Preferred DSL Path

Recommended flow:

```text
request
-> qa-entrypoint
-> agent-plan-authoring
-> authoring-plan.yaml
-> validate
-> compile or generate
```

If `authoring-plan.yaml` sets `defaults.actor`, preserve it through compile/render. The resulting
scenario variable `actor = literal:<value>` is the execution-profile hook for actor-scoped env keys
such as `API_BASE_URL__API_CLIENT` and `DATABASE_URL__API_CLIENT`.

Commands:

```powershell
<venv-python> -m tools.generation.cli `
  --validate-authoring-plan `
  --authoring-plan-file <file> `
  --output-format text

<venv-python> -m tools.generation.cli `
  --compile-authoring-plan `
  --authoring-plan-file <file> `
  --output artifacts/agent/generation `
  --output-format text

<venv-python> -m tools.generation.cli `
  --authoring-plan-file <file> `
  --workspace-root .
```

## Compiled Low-Level Path

```powershell
<venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --output-format text

<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root .
```

## Prose Fallback

```powershell
<venv-python> -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user and get user by id" `
  --workspace-root .
```
