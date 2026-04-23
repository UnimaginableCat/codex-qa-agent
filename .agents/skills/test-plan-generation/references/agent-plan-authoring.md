# Agent Plan Authoring

## Standard Authoring Workflow

1. Scaffold a starter JSON.
2. Fill the top-level plan fields.
3. Expand `planned_test_cases[]`.
4. Add assumptions and open questions explicitly.
5. Validate before generation.
6. Run generation with `--agent-plan-file`.

## Scaffold Command

```powershell
<venv-python> -m tools.generation.cli `
  --init-agent-plan `
  --output artifacts/agent/input/users-api-plan.json `
  --source-id users-api `
  --project code/demo `
  --name "Users API" `
  --goal "Cover user API behavior."
```

## Validate Command

```powershell
<venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/input/users-api-plan.json `
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
- optional `evidence_scope`
- optional `metadata`

Each case should contain:

- `title`
- `objective`
- `kind`
- `preconditions[]`
- `actions[]`
- `expected_outcomes[]`
- `priority`
- `tags[]`
- `unresolved_items[]`
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

Status behavior:

- `PASS`: valid authoring input
- `BLOCKED`: required fields missing
- `ERROR`: malformed JSON or unsupported structure

## Authoring Guidance

Write only what the agent can justify.

- Keep `actions[]` at planning level, not runner-step level.
- Use `expected_outcomes[]` for testable outcomes, not implementation guesses.
- Put uncertain details into `unresolved_items[]` or `open_questions[]`.
- Use `assumptions[]` only for stable assumptions the plan depends on.
- Do not hide primary planning fields inside `metadata`.

## When To Add `evidence_scope`

Add `evidence_scope` only when the next phase is expected to collect code facts. If no evidence
phase is needed yet, leave it out and keep authoring focused on the plan itself.
