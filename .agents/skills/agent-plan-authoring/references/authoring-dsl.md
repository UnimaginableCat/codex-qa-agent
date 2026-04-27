# Authoring DSL MVP

`authoring-plan.yaml` is the LLM-facing contract for test-plan authoring.

In the managed workflow, the editable DSL source normally lives at
`artifacts/agent/generation/<run_id>/authoring-plan.yaml`.

MVP decisions:

- YAML first
- deterministic compiler
- no free-form setup prose
- reusable setup/persistence templates live under `entities`

Minimal shape:

```yaml
version: 1
source_id: users-controller-plan
project: code/demo-project
title: Users controller coverage
goal: Verify main CRUD and validation flows for users API

scope:
  surface: users-controller
  style: api-first
  include:
    - create user
    - get user
    - update user
    - delete user

defaults:
  environment: env/demo.env
  auth: bearer
  actor: admin-api-client

entities: {}
cases: []
```

The example actor `admin-api-client` maps to actor-scoped env keys such as
`API_BASE_URL__ADMIN_API_CLIENT` and `DATABASE_URL__ADMIN_API_CLIENT`.

Compiler behavior:

- expands `setup[]` via `entities.*.operations.*`
- maps compact route/oracle definitions into `AgentTestPlanInput`
- resolves persisted-state verification via entity DB templates
- carries `defaults.environment` into rendered scenario `## Environment`
- carries `defaults.actor` into rendered scenario `## Variables` as `actor = literal:<value>`
- uses that rendered `actor` variable to select actor-scoped API/DB env keys like `API_BASE_URL__API_CLIENT` or `DATABASE_URL__API_CLIENT`, with fallback to base keys
- uses `defaults.auth` as fallback auth strategy when case/setup API auth is not authored explicitly
- runs existing `validate_agent_plan_input(...)` after compilation

Supported `state_change` values:

- mutating: `create`, `update`, `delete`, `mutate`
- read-only: `none`, `read_only`, `readonly`
- case ids must be unique within one authoring plan

Compiler does not:

- invent SQL
- infer missing route templates
- infer missing capture targets
- interpret broad prose as executable detail
