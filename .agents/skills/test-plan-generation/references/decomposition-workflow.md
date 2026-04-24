# Decomposition Workflow

## Purpose

Transform a broad feature/controller request into a high-quality `AgentTestPlanInput`.

## Core Method

1. Identify scope.
2. Extract concrete operations.
3. Define coverage buckets.
4. Expand planned test cases.
5. Add assumptions and open questions.
6. Align API/DB cases with downstream scenario syntax.

## Compact-First Rule

- Start with roughly `8-10` strong cases unless the user explicitly wants exhaustive coverage.
- Prefer operation-first coverage over branch-by-branch code inventory.
- Merge internal branches that collapse to the same observable API behavior.
- Keep authored `expected_outcomes[]` compatible with downstream scenario syntax.
- For broad controller requests, do not author all executable detail in one pass. First prove the shape on `1-2` representative seed cases, then expand the full scope.

## Step Guidance

### Identify Scope

Determine:

- target project
- controller/feature/workflow boundary
- whether the request is API-focused, lifecycle-focused, validation-focused, or mixed

### Extract Concrete Operations

Look for named operations first:

- `list`
- `get`
- `create`
- `update`
- `patch`
- `delete`
- `revoke`
- `revoke all`
- `authenticate`
- `transition`

### Define Coverage Buckets

Common buckets:

- happy path
- validation
- missing entity / not found
- invalid transition / forbidden operation
- collection vs item behavior

### Expand Planned Test Cases

Good case pattern:

- title names operation + bucket
- objective states confirmed behavior
- actions stay at plan level
- `observable_outcomes[]` stay human-readable
- `expected_outcomes[]` stay executable

Execution-first pattern:

- pick a small seed set that exercises the main request shapes first, for example one single-endpoint happy path and one mutating workflow
- make those seed cases fully executable before expanding the rest
- if a field is normalized or transformed by the system, model both input and expected output explicitly with separate variables
- avoid prose bundles like "send several invalid payloads" unless they are rendered as separate executable workflow steps

For full workflows:

- use one case with `workflow_steps[]`
- add persisted-state verification when the workflow mutates state successfully

### Add Assumptions And Open Questions

- `assumptions[]` for stable plan-wide assumptions
- `open_questions[]` for plan-wide unresolved items
- `unresolved_items[]` for case-specific ambiguity

### Align With Downstream Syntax

Prefer adding:

- `route` for single-endpoint API cases
- `workflow_steps[]` for multi-step flows
- DSL-compatible `expected_outcomes[]`
- `capture[]` when later steps need captured values
- `request_body` / `requires_request_body` when request shape matters
- `auth_strategy[]` / `requires_auth_strategy` when auth is not implicit
- `db_verification` / `requires_db_verification` when persisted state is part of the contract
- derived/template variables when expectations depend on normalized output values rather than raw request values
