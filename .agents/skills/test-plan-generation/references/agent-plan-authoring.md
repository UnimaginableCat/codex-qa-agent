# Agent Plan Authoring

## Standard Authoring Workflow

1. Scaffold a starter JSON.
2. Fill the top-level plan fields.
3. Expand `planned_test_cases[]`.
4. Add assumptions and open questions explicitly.
5. Validate before generation.
6. Run generation with `--agent-plan-file`.

The agent should do this by default for decomposable requests. The user does not need to explicitly
ask for scaffold/validate steps.

## Scaffold Command

```powershell
<venv-python> -m tools.generation.cli `
  --init-agent-plan `
  --output artifacts/agent/generation `
  --source-id users-api `
  --project code/demo `
  --name "Users API" `
  --goal "Cover user API behavior."
```

## Validate Command

```powershell
<venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
  --output-format text
```

When `expected_outcomes[]` or `capture[]` use unsupported syntax, prefer the validator output over
manual source diving. The text output now includes:

- the exact invalid rule
- a short DSL hint
- supported examples

Do not inspect old plan artifacts just to rediscover the supported expectation syntax.

After generation, the authored input is persisted again inside the request bundle as
`artifacts/agent/generation/<source>-<run_id>/agent-plan.json`. Treat that bundle copy as the
canonical request artifact, not the temporary scaffold path.

## Canonical Shape

Top-level fields:

- `source_id`
- `project`
- `title`
- `goal`
- `planned_test_cases[]`
- `assumptions[]`
- `open_questions[]`
- optional `evidence_scope`
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

Validation checks:

- file exists and is valid JSON
- payload is a JSON object
- required top-level fields are present
- at least one planned case exists
- each case has `title`
- each case has `objective`
- list/object fields use supported JSON shapes
- API/DB `expected_outcomes[]` use supported scenario expectation syntax rather than free-form narrative
- `capture[]` uses supported capture syntax when present
- `requires_request_body=true` requires `request_body`
- `requires_auth_strategy=true` requires explicit auth strategy or authored auth headers
- `requires_db_verification=true` requires explicit `db_verification`

Status behavior:

- `PASS`: valid authoring input
- `BLOCKED`: required fields missing
- `ERROR`: malformed JSON or unsupported structure

## Authoring Guidance

Write only what the agent can justify.

- Keep `actions[]` at planning level, not runner-step level.
- For API/DB cases, use `observable_outcomes[]` for human-readable behavior and `expected_outcomes[]` for runner-compatible assertion DSL.
- Use `capture[]` only when later scenario steps or DB verification need captured values.
- Put uncertain details into `unresolved_items[]` or `open_questions[]`.
- Use `assumptions[]` only for stable assumptions the plan depends on.
- Do not hide primary planning fields inside `metadata`.
- Do not ask the user to prescribe the JSON structure unless a true ambiguity remains.

For API-heavy plans, prefer authoring cases that are already grounded enough for:

- request structure
- auth strategy
- executable expectations
- capture needs
- optional DB verification

This reduces drift between the authored plan and downstream scenario drafts.

If validation fails on expectation DSL, rewrite the authored rule into the supported syntax instead
of weakening the case objective. For example:

- bad: `Missing-user response status is 404.`
- good: `HTTP 404`
- bad: `Successful response returns session JSON.`
- good: `HTTP 200`
- good: `response JSON exists`

## When To Add `evidence_scope`

Add `evidence_scope` only when the next phase is expected to collect code facts. If no evidence
phase is needed yet, leave it out and keep authoring focused on the plan itself.
