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
  headers:
    X-Internal-Token: "{{internal_api_token}}"
  scenario_variables:
    - run_suffix = generated:run_suffix
    - internal_api_token = env:INTERNAL_API_TOKEN

entities: {}
cases: []
```

The example actor `admin-api-client` maps to actor-scoped env keys such as
`API_BASE_URL__ADMIN_API_CLIENT` and `DATABASE_URL__ADMIN_API_CLIENT`.

If an entity defines `id_field`, treat it as the canonical variable name for that entity instance,
for example `user_id`. Setup chains should capture it before later setup operations reuse it, and
persisted-state DB templates should reference it so verification stays scoped to the authored entity.

Compiler behavior:

- expands `setup[]` via `entities.*.operations.*`
- maps compact route/oracle definitions into `AgentTestPlanInput`
- resolves persisted-state verification via entity DB templates
- carries `defaults.environment` into rendered scenario `## Environment`
- carries `defaults.actor` into rendered scenario `## Variables` as `actor = literal:<value>`
- merges `defaults.headers` into authored API/workflow request headers, with case-level and entity-operation headers taking precedence on key conflicts
- carries first-class `defaults.scenario_variables[]` and `cases[].scenario_variables[]` into rendered scenario `## Variables`
- uses that rendered `actor` variable to select actor-scoped API/DB env keys like `API_BASE_URL__API_CLIENT` or `DATABASE_URL__API_CLIENT`, with fallback to base keys
- uses `defaults.auth` as fallback auth strategy when case/setup API auth is not authored explicitly
- runs existing `validate_agent_plan_input(...)` after compilation

Downstream note:

- standalone `db-check` authoring cases compile correctly, but they are not the default choice for controller coverage when the next stages are `render -> review -> promote`
- current draft rendering favors authored API routes and workflow steps; a pure schema-readiness `db-check` may remain deferred instead of becoming a promoted markdown scenario
- for controller coverage, prefer API/workflow cases with persisted-state DB verification over a separate schema-readiness case unless the user explicitly asks for schema verification

Expectation syntax is strict. Author only compile-safe checks.

Supported API checks include:

- `HTTP 200`
- `HTTP 200 or HTTP 201`
- `response JSON exists`
- `response JSON is an array`
- `response contains field \`id\``
- `response \`status\` = \`ACTIVE\``
- `response \`createdAt\` is not null`
- `response \`items\` length >= 1`

Normalized-field guidance:

- when the request intentionally sends mixed-case or padded input that the product may normalize, do not reuse the same placeholder in output expectations
- for fields like `email`, author separate variables for submitted input and expected stored/returned value
- example:
  - `submitted_email = template:AUTOTEST.User.{{email_suffix}}@Example.COM`
  - `expected_email = derived:submitted_email|lower`
  - request body: `email: "{{submitted_email}}"`
  - expectation: `response \`email\` = \`{{expected_email}}\``

Supported DB checks include:

- `one row exists`
- `no rows exist`
- `` `status` = `ACTIVE` ``
- `` `email` is null ``
- `` `created_at` is not null ``
- `` `email` starts with `autotest.` ``

Avoid unsupported prose-like checks such as:

- `response error exists`
- `response JSON array exists`
- `response array contains a user with ...`
- `response indicates ...`
- `response email is null or omitted`
- `display_name = LeadFlow User` without backticks in DB expectations

Capture syntax is strict too:

- good: `response.json.id -> user_id`
- bad: `capture response id as user_id`

Variable syntax is strict too:

- good: `run_suffix = generated:run_suffix`
- good: `internal_api_token = env:INTERNAL_API_TOKEN`
- good: `primary_email = template:autotest.{{run_suffix}}@example.com`
- bad: `run_suffix generated dynamically`
- bad: `internal token from env`
- bad: `display_name = Fixed literal without literal prefix`

Header guidance:

- use `defaults.headers` for shared non-secret or env-backed headers across many requests
- use per-case `execute.headers` or entity-operation `request_headers` when a header is specific to one flow
- if the same header appears in both `defaults.headers` and a case or entity operation, the more specific authored header wins
- do not invent custom `defaults.auth` values for header-based auth schemes; model them as explicit headers instead

Supported `state_change` values:

- mutating: `create`, `update`, `delete`, `mutate`
- read-only: `none`, `read_only`, `readonly`
- case ids must be unique within one authoring plan

Compiler does not:

- invent SQL
- infer missing route templates
- infer missing capture targets
- interpret broad prose as executable detail
- use `metadata.scenario_variables` as the primary authoring path; use first-class `scenario_variables` fields instead
