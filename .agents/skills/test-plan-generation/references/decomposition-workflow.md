# Decomposition Workflow

## Purpose

This workflow explains how the agent should transform a broad feature/controller request into a
high-quality `AgentTestPlanInput`.

The intent is deterministic decomposition, not prose summarization and not speculative design.

## Core Method

1. Identify scope.
2. Extract concrete operations.
3. Define coverage buckets.
4. Expand planned test cases.
5. Add assumptions and open questions.
6. Optionally define evidence scope.

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

## Step 4 - Expand Planned Test Cases

Turn operations plus buckets into cases.

Good case pattern:

- title names the operation + bucket
- objective says what behavior is being confirmed
- actions stay at plan level
- expected outcomes are explicit but conservative

Examples:

- `Authenticate session happy path`
- `List sessions`
- `Get session by id`
- `Get session by id when entity is missing`
- `Revoke single session`
- `Revoke all sessions`

## Step 5 - Add Assumptions And Open Questions

Use:

- `assumptions[]` for stable plan-wide assumptions
- `open_questions[]` for plan-wide unresolved items
- `unresolved_items[]` for case-specific ambiguity

Examples:

- assumption: "Authorized internal operator credentials are available."
- open question: "Which auth fixture should be used?"
- unresolved item: "Exact endpoint path should be confirmed from code facts."

## Step 6 - Optionally Define Evidence Scope

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
      "expected_outcomes": [
        "A new session is created and returned."
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
      "expected_outcomes": [
        "Existing sessions are returned as a collection."
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
      "expected_outcomes": [
        "The requested session is returned."
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
      "expected_outcomes": [
        "The controller returns the missing-entity behavior defined by the API."
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
      "expected_outcomes": [
        "The targeted session is revoked."
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
      "expected_outcomes": [
        "All targeted active sessions are revoked."
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
- Do not guess DTO fields, DB behavior, or auth details when they are not known.
- Do not turn planning actions into runner-ready steps at this phase.
- Do not add evidence scope unless the next phase will actually use it.
