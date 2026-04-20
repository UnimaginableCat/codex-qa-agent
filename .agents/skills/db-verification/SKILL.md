---
name: db-verification
description: Use this skill to execute read-only database verification steps for a scenario, validate actual persisted state, and provide evidence for the final QA report.
---

# Purpose

This skill verifies whether the system state in the database matches expectations after scenario execution.

Use this skill when:
- a scenario step is of type DB
- the user wants post-action verification
- you need to confirm inserts, updates, statuses, or related records

# Inputs to read

- the current DB step
- the scenario environment path
- `env/<project>.env`
- prior step outputs
- code-analysis findings about expected persistence behavior

# Execution workflow

1. Read the DB step carefully.
2. Resolve:
   - SQL query
   - params
   - dependencies on prior steps
3. Ensure the query is read-only.
4. Before execution, use `env-resolution` if the environment path or database connection settings are unclear.
5. Load the correct env file.
6. Execute the query through `tools/db/query_check.py`.
7. Compare returned rows to expected outcomes.
8. Record the result and supporting evidence.

# Validation rules

Check as applicable:
- row exists / row count
- specific column values
- status fields
- foreign key relationships
- timestamps or audit rows if relevant
- consistency with expected side effects from code analysis

# Status rules

- PASS — query executed and returned expected data
- FAIL — query executed but returned unexpected data
- BLOCKED — missing DB config/access or disallowed query
- ERROR — tool/runtime/database failure

# Guardrails

- Allow only read-only SELECT queries.
- Never mutate data.
- Never mark missing DB access as FAIL.
- If the SQL is ambiguous or not aligned with the code path, say so clearly.

# Completion criteria

This skill is complete when the database verification step has:
- been executed or clearly marked BLOCKED/ERROR
- been validated against expectations
- produced evidence usable in the final report