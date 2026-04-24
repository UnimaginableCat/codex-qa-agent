# Agent Plan Authoring

## Standard Workflow

1. Scaffold a starter JSON.
2. Fill top-level plan fields.
3. Author `1-2` representative seed cases first.
4. Validate before scaling the rest of `planned_test_cases[]`.
5. Expand the remaining cases only after the seed cases are structurally executable.
6. Add assumptions and open questions explicitly.
7. Validate before generation.
8. Run generation with `--agent-plan-file`.

## Scaffold

```powershell
<venv-python> -m tools.generation.cli `
  --init-agent-plan `
  --output artifacts/agent/generation `
  --source-id users-api `
  --project code/demo `
  --name "Users API" `
  --goal "Cover user API behavior."
```

## Validate

```powershell
<venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --output-format text
```

## Canonical Shape

Top-level fields:

- `source_id`
- `project`
- `title`
- `goal`
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

## Seed-Case Gate

Before expanding a broad controller or feature request into the full case set, make sure the first `1-2` authored cases already satisfy all of the following:

- deterministic `expected_outcomes[]` using supported DSL
- complete `route` or `workflow_steps[]`
- required `capture[]` rules when later steps depend on earlier values
- persisted-state verification for successful mutating workflows
- normalization-aware expected values

If those gates are not met, fix the seed cases first instead of adding more cases.
