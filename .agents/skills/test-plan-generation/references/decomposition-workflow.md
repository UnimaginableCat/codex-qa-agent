# Decomposition Workflow

## Purpose

This workflow explains how the agent should transform a broad feature/controller request into a
high-quality `AgentTestPlanInput`.

The intent is deterministic decomposition, not prose summarization and not speculative design.

This is an internal agent workflow. The user should usually be able to ask for coverage in one
short sentence without restating decomposition rules.

## Core Method

1. Identify scope.
2. Extract concrete operations.
3. Define coverage buckets.
4. Expand planned test cases.
5. Add assumptions and open questions.
6. Align API/DB cases with downstream scenario syntax.
7. Optionally define evidence scope.

## Compact-First Rule

For controller/API requests, the initial plan should be compact by default.

- Start with roughly `8-10` strong cases unless the user explicitly wants exhaustive coverage.
- Prefer operation-first coverage over branch-by-branch code inventory.
- If several internal branches collapse to the same observable API behavior, merge them into one case.
- Do not treat every internal outcome as a separate test case unless it is meaningfully distinct at the API contract level.
- For `kind=api` and `kind=db`, keep the authored case compatible with downstream scenario expectations instead of leaving assertions as narrative prose.

## Default Trigger

Trigger this workflow by default when the request names:

- a controller
- an API surface
- a feature/workflow
- a lifecycle/state-transition area
- a validation-heavy operation

Example short request:

```text
project: code/beck-end-1.0
request: Проверить полный функционал InternalUserSessionController
```

This should normally go through decomposition, not prose bootstrap.

## Step 1 - Identify Scope

Determine:

- target project
- controller/feature/workflow boundary
- whether the request is API-focused, lifecycle-focused, validation-focused, or mixed

Examples:

- `InternalUserSessionController` -> likely controller/API surface scope
- "price list creation" -> feature/workflow scope
- "invalid status transition" -> lifecycle/state constraint scope

Do not decompose across the entire repository unless the user explicitly asked for cross-cutting coverage.

If scope is still ambiguous after a narrow read of the request, ask only the smallest clarifying
question needed to choose the right boundary.

## Step 2 - Extract Concrete Operations

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

For a REST controller, these operations are often the first stable case anchors.

## Step 3 - Define Coverage Buckets

For each operation, decide which buckets matter:

- happy path
- validation
- missing entity / not found
- invalid transition / forbidden operation
- collection vs item behavior
- boundary/empty state behavior

Do not expand every bucket blindly. Use only buckets that are justified by the request or obvious operation semantics.

When the request is API-heavy, prefer buckets that naturally map to distinct endpoint contracts.
This keeps later coverage assessment against extracted endpoint facts useful instead of noisy.

## Step 4 - Expand Planned Test Cases

Turn operations plus buckets into cases.

Good case pattern:

- title names the operation + bucket
- objective says what behavior is being confirmed
- actions stay at plan level
- `observable_outcomes[]` keep the human-readable behavior
- `expected_outcomes[]` stay executable and scenario-compatible for API/DB cases

For full workflow coverage, prefer a second pattern:

- one case proves the end-to-end lifecycle
- `workflow_steps[]` encode the concrete multi-step API/DB path inside that single case
- if the workflow mutates persisted state and succeeds, include a read-only DB confirmation either as `db_verification` or as a final `workflow_steps[]` DB step
- single-endpoint cases remain for isolated validation/not-found buckets

Examples:

- `Authenticate session happy path`
- `List sessions`
- `Get session by id`
- `Get session by id when entity is missing`
- `Revoke single session`
- `Revoke all sessions`

While expanding cases:

- keep the case set compact
- prefer observable differences over internal cause differences
- avoid field-by-field DTO assertions unless those fields are central to the public contract
- avoid vague API expectations like "entity is returned successfully" when the downstream assertion DSL is already known
- do not model a full user journey as three disconnected single-endpoint happy-path cases when one e2e workflow case would better prove the behavior

## Step 5 - Add Assumptions And Open Questions

Use:

- `assumptions[]` for stable plan-wide assumptions
- `open_questions[]` for plan-wide unresolved items
- `unresolved_items[]` for case-specific ambiguity

Examples:

- assumption: "Authorized internal operator credentials are available."
- open question: "Which auth fixture should be used?"
- unresolved item: "Exact endpoint path should be confirmed from code facts."

## Step 6 - Align API/DB Cases With Downstream Scenario Syntax

For `kind=api` and `kind=db`, author the case so it can survive draft rendering without semantic
drift.

Prefer adding:

- `observable_outcomes[]` for human-readable behavior
- DSL-compatible `expected_outcomes[]`
- `capture[]` when later checks need captured values
- `request_body` / `requires_request_body` when the request shape matters
- `auth_strategy[]` / `requires_auth_strategy` when auth is not implicit
- `db_verification` / `requires_db_verification` when persisted state is part of the contract
- for successful state-changing workflow cases, assume persisted state is part of the contract unless the user explicitly scoped the request to transport-only API checks

If the agent cannot justify a concrete assertion yet, keep it as an explicit unknown instead of
writing narrative `expected_outcomes[]` that downstream tooling cannot preserve.

## Step 7 - Optionally Define Evidence Scope

If the next phase should enrich from code facts, define narrow scope such as:

- one controller file
- one explicit API module
- one narrow directory with controller classes

Do not define repository-wide evidence scope by default.

## Common Patterns

### REST Controller

Default decomposition pattern:

- list
- get by id
- create
- update/patch
- delete/revoke if applicable
- missing entity
- validation failures where obvious

### Lifecycle / State Transition

Default pattern:

- allowed transition
- invalid transition
- transition from missing entity
- side-effect or state confirmation if requested

### Validation-Heavy Endpoint

Default pattern:

- valid payload
- missing required field
- invalid format/value
- duplicate/conflict if implied

### List / Get / Create / Update / Revoke Style API

Use operation-first decomposition and then add the one or two most relevant negative buckets per operation.

## Worked Example

Input request:

```text
Проверить полный функционал InternalUserSessionController
```

Reasonable decomposition:

```json
{
  "source_id": "internal-user-session-controller",
  "project": "code/demo",
  "title": "InternalUserSessionController coverage",
  "goal": "Cover core InternalUserSessionController operations and key negative cases.",
  "assumptions": [
    "Internal operator credentials are available for session-related checks."
  ],
  "open_questions": [
    "Exact route paths should be confirmed from controller code facts."
  ],
  "planned_test_cases": [
    {
      "title": "Authenticate session happy path",
      "objective": "Verify the controller can create/authenticate an internal user session.",
      "kind": "api",
      "preconditions": [
        "Valid internal user credentials are available."
      ],
      "actions": [
        "Call the authenticate session operation with valid credentials."
      ],
      "observable_outcomes": [
        "A new session is created and returned."
      ],
      "expected_outcomes": [
        "HTTP 200 or HTTP 201",
        "response JSON exists"
      ],
      "priority": "high",
      "tags": [
        "session",
        "authenticate",
        "happy-path"
      ],
      "unresolved_items": [
        "Exact endpoint path should be resolved from code facts."
      ]
    },
    {
      "title": "List sessions",
      "objective": "Verify active sessions can be listed.",
      "kind": "api",
      "preconditions": [],
      "actions": [
        "Call the list sessions operation."
      ],
      "observable_outcomes": [
        "Existing sessions are returned as a collection."
      ],
      "expected_outcomes": [
        "HTTP 200",
        "response JSON is an array"
      ],
      "priority": "normal",
      "tags": [
        "session",
        "list"
      ],
      "unresolved_items": [
        "Collection filters/sort behavior is not specified."
      ]
    },
    {
      "title": "Get session by id",
      "objective": "Verify one session can be retrieved by identifier.",
      "kind": "api",
      "preconditions": [
        "A valid session identifier exists."
      ],
      "actions": [
        "Call the get session operation with a valid session id."
      ],
      "observable_outcomes": [
        "The requested session is returned."
      ],
      "expected_outcomes": [
        "HTTP 200",
        "response JSON exists"
      ],
      "priority": "normal",
      "tags": [
        "session",
        "get"
      ],
      "unresolved_items": [
        "Identifier path variable name should be confirmed."
      ]
    },
    {
      "title": "Get session by id when entity is missing",
      "objective": "Verify missing session lookup is handled correctly.",
      "kind": "api",
      "preconditions": [],
      "actions": [
        "Call the get session operation with a non-existent session id."
      ],
      "observable_outcomes": [
        "The controller returns the missing-entity behavior defined by the API."
      ],
      "expected_outcomes": [
        "HTTP 404"
      ],
      "priority": "normal",
      "tags": [
        "session",
        "get",
        "negative"
      ],
      "unresolved_items": [
        "Exact status code/error shape is not yet confirmed."
      ]
    },
    {
      "title": "Revoke single session",
      "objective": "Verify one session can be revoked.",
      "kind": "api",
      "preconditions": [
        "A revocable active session exists."
      ],
      "actions": [
        "Call the revoke session operation for one session."
      ],
      "observable_outcomes": [
        "The targeted session is revoked."
      ],
      "expected_outcomes": [
        "HTTP 200 or HTTP 204"
      ],
      "priority": "normal",
      "tags": [
        "session",
        "revoke"
      ],
      "unresolved_items": [
        "Post-revoke verification strategy is not selected."
      ]
    },
    {
      "title": "Revoke all sessions",
      "objective": "Verify all relevant sessions can be revoked in one operation.",
      "kind": "api",
      "preconditions": [
        "Multiple active sessions exist."
      ],
      "actions": [
        "Call the revoke-all operation."
      ],
      "observable_outcomes": [
        "All targeted active sessions are revoked."
      ],
      "expected_outcomes": [
        "HTTP 200 or HTTP 204"
      ],
      "priority": "normal",
      "tags": [
        "session",
        "revoke-all"
      ],
      "unresolved_items": [
        "Exact target population of revoke-all should be confirmed."
      ]
    }
  ]
}
```

## What Not To Do

- Do not create one giant generic case like "check full controller functionality".
- Do not explode one controller into a large branch inventory by default.
- Do not guess DTO fields, DB behavior, or auth details when they are not known.
- Do not turn planning actions into runner-ready steps at this phase.
- Do not add evidence scope unless the next phase will actually use it.
- Do not leave uncovered endpoint facts unaddressed after collecting code facts; use missing-case suggestions to repair the decomposition before polishing drafts.

## Quality Gate

Before generation, quickly check the plan against this gate:

- `compact`
- `observable`
- `non-duplicative`
- `render-friendly`
- `scenario-aligned`
- `explicit-unknowns`

If the plan fails the gate, reduce or reshape it before generation.
