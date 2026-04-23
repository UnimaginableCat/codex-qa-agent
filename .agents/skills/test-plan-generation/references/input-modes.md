# Input Modes

## Primary Rule

`agent_plan` is the primary input path.

Use `AgentTestPlanInput` when the agent can already decompose the request into explicit planned
cases. This is the normal path for controller/feature requests such as:

- "Проверить полный функционал InternalUserSessionController"
- "Нужен тест-план на internal tenants API"
- "Покрыть lifecycle and validation cases for create/update flow"

This path is preferred because it preserves agent reasoning explicitly instead of forcing a broad
request through prose scanning first.

## Fallback Rule

Use prose mode only when one of these is true:

- the request is too vague to decompose yet
- the operator explicitly asks for prose-first/bootstrap generation
- the request is so small that structured authoring adds no real value

Prose mode is compatibility/bootstrap only. It should not be the default for broad feature or
controller requests.

## Mode Selection

Choose `agent_plan` when:

- scope is clear enough to enumerate operations or coverage buckets
- the agent can name likely cases directly
- the request targets a controller, API surface, workflow, validation area, or lifecycle

Choose prose when:

- scope is still unclear and the next best step is just to capture operator wording
- the user wants a rough seed plan
- decomposition would be mostly guessing

## Minimal Commands

Structured plan:

```powershell
<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/input/users-api-plan.json `
  --workspace-root .
```

Prose fallback:

```powershell
<venv-python> -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user and get user by id" `
  --workspace-root .
```

## What Not To Do

- Do not mix structured decomposition and prose fallback in one opaque request.
- Do not treat prose mode as the standard path for controller-level coverage.
- Do not use prose mode to avoid decomposition when the request already implies real operations.
