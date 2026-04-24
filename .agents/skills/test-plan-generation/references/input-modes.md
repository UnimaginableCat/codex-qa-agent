# Input Modes

## Primary Rule

Use `agent_plan` whenever the request is decomposable into explicit operations or behaviors.

Use prose only when:

- the request is too vague to decompose responsibly yet
- the user explicitly wants a prose bootstrap
- structured authoring would add unnecessary overhead

## Structured Path

Recommended flow:

```text
request -> agent plan scaffold -> authored cases -> validate -> generate
```

Commands:

```powershell
<venv-python> -m tools.generation.cli `
  --init-agent-plan `
  --output artifacts/agent/generation `
  --source-id users-api `
  --project code/demo `
  --name "Users API"

<venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
  --output-format text

<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
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
