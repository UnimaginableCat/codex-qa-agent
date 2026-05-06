# Compiled Plan Escape Hatch

## Primary Rule

The normal skill-routed path is:

1. use `qa-entrypoint` when the request is broad
2. scaffold or refine the staged bundle through `agent-plan-authoring`
   - `entity-inventory.yaml`
   - `operation-inventory.yaml`
   - `authoring-plan.yaml`
3. run `--validate-authoring-bundle --path artifacts/agent/generation/<run_id>`
4. only then compile or generate through `test-plan-generation`

Use direct `agent-plan.json` work only when the user explicitly wants manual structured control or
when you are debugging or repairing a compiled bundle.

## Direct Structured Workflow

```powershell
<venv-python> -m tools.generation.cli `
  --init-agent-plan `
  --output artifacts/agent/generation `
  --source-id users-api `
  --project code/demo `
  --name "Users API" `
  --goal "Cover user API behavior."
```

Fill the scaffolded `agent-plan.json`, then validate and generate from it:

```powershell
<venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --output-format text

<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root .
```

## When To Use This Path

- repairing one compiled bundle without going back to authoring DSL
- inspecting compiler output directly
- reproducing a low-level generation defect
- fulfilling an explicit user request for `agent-plan.json`

## Canonical Shape

Top-level fields:

- `source_id`
- `project`
- `title`
- `goal`
- optional `scenario_variables[]`
- `planned_test_cases[]`
- `assumptions[]`
- `open_questions[]`
- optional `metadata`

Each case should contain:

- `title`
- `objective`
- `kind`
- `preconditions[]`
- `actions[]`
- optional `observable_outcomes[]`
- `expected_outcomes[]`
- optional `capture[]`
- optional `workflow_steps[]`
- `priority`
- `tags[]`
- `unresolved_items[]`
- optional `route`
- optional `request_headers`
- optional `request_params`
- optional `request_body`
- optional `requires_request_body`
- optional `auth_strategy[]`
- optional `requires_auth_strategy`
- optional `db_verification`
- optional `requires_db_verification`
- optional `assumptions[]`
- optional `scenario_variables[]`
- optional `metadata`

## Validation Rules

- file exists and is valid JSON
- payload is a JSON object
- required top-level fields are present
- at least one planned case exists
- each case has `title`
- each case has `objective`
- API/DB `expected_outcomes[]` use supported scenario expectation syntax
- `capture[]` uses supported capture syntax when present
- `requires_request_body=true` requires `request_body`
- `requires_auth_strategy=true` requires explicit auth strategy or authored auth headers
- `requires_db_verification=true` requires explicit `db_verification`

## Authoring Guidance

- Treat `defaults.actor` as an execution profile selector. It should represent the concrete client,
  role, or subject whose env-scoped credentials/base URLs should be used at runtime.
- Use stable actor names because they map into env keys by uppercasing and replacing non-alphanumeric
  characters with `_`, for example `api-client -> API_CLIENT`.
- Do not author `defaults.actor` as prose-only business commentary; if it is present, downstream
  runtime will use it to select actor-scoped `API_*` and `DATABASE_*` keys before falling back to
  base env values.
- Workflow steps may set `actor` when a single scenario must switch roles, for example founder
  performs a permission grant and partner performs the gated action. Rendered markdown preserves
  this as step-level `Actor: <role>`, and runtime uses it before the scenario-level actor variable.
- For shared custom headers in authoring DSL, prefer `defaults.headers` with env-backed variables,
  for example `X-Leadflow-Internal-Token: "{{internal_api_token}}"`.
- Do not model custom header auth schemes as invented `defaults.auth` values; keep them as explicit
  headers and let runtime-supported auth types stay limited to the real enum.
- Keep `actions[]` at planning level, not runner-step level.
- Use `workflow_steps[]` for true cross-endpoint lifecycle coverage.
- For successful mutating workflows, include persisted-state verification.
- Use `observable_outcomes[]` for human-readable behavior and `expected_outcomes[]` for runner-compatible assertions.
- For DB steps, prefer direct row-shape assertions like `one row exists` / `no rows exist` before falling back to aggregate SQL.
- Treat `agent-plan.json` as execution-ready source material. Do not rely on later render/review phases to hand-fix core DSL or workflow-shape issues.
- For normalized outputs, separate raw input variables from expected output variables. Example: keep a mixed-case email input variable and a lower-cased expected email variable instead of asserting normalized output against the raw input placeholder.
- Do not use raw placeholders in expectations when the API is expected to trim, lowercase, derive, or otherwise transform the submitted value.
- Split distinct invalid variants into separate cases or explicit workflow steps so each request remains executable and independently assertable.
- If a case is intended for downstream execution, do not leave it in a prose-only state after validation; add the concrete `route` or full `workflow_steps[]`, request details, captures, and DB verification that the runner will need.
- Put uncertain details into `unresolved_items[]` or `open_questions[]`.
- Do not hide primary planning fields inside `metadata`.
- Use first-class `scenario_variables[]` for machine-readable variables that must survive compile, normalize, render, and promotion.
- Keep env-backed variables explicit, for example `internal_api_token = env:INTERNAL_API_TOKEN`, and rely on preflight to resolve them.

## Seed-Case Gate

Before expanding a broad controller or feature request into the full case set, make sure the first
`1-2` authored cases already satisfy all of the following:

- deterministic `expected_outcomes[]` using supported DSL
- complete `route` or `workflow_steps[]`
- required `capture[]` rules when later steps depend on earlier values
- persisted-state verification for successful mutating workflows
- normalization-aware expected values

If those gates are not met, fix the seed cases first instead of adding more cases.
