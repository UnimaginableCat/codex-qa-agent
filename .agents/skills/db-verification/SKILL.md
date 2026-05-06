---
name: db-verification
description: Use this skill to execute read-only database verification steps for a scenario, validate actual persisted state, and provide evidence for the final QA report.
---

# Purpose

This skill verifies whether the system state in the database matches expectations after scenario execution.

Apply the shared workspace instructions from `qa-entrypoint` first. This skill adds DB-step execution and SQL-specific rules.

Use this skill when:
- a scenario step is of type DB
- the user wants post-action verification
- you need to confirm inserts, updates, statuses, or related records

# Inputs to read

- the current DB step
- the scenario environment path
- `env/<project>.env`
- prior step outputs
- code-analysis findings only if additional clarification is needed

# Execution workflow

1. Read the DB step carefully.
2. Resolve:
   - SQL query
   - params
   - dependencies on prior steps
3. Resolve scenario variables in SQL and params from:
   - explicit scenario values
   - prior captured outputs
   - environment values if appropriate
   - machine-readable derived/template variables such as `derived:run_suffix|lower` and `template:...`

Do not treat prose variable descriptions as values. Invalid variable definitions must block before DB verification so malformed placeholders do not turn into unsupported expectation rules or misleading DB checks.
4. Ensure the query is read-only.
5. Before execution, use `env-resolution` if the environment path or database connection settings are unclear.
6. Load the correct env file.
7. Execute the query through `tools/db/query_check.py`.
8. Compare returned rows to expected outcomes.
9. Record the result and supporting evidence.

Do not hand-roll DB checks with inline `psycopg`, direct connection strings, or custom dotenv parsing. The DB tool owns actor-scoped env overlay, read-only guarding, named parameter adaptation, JSON-safe output, and structured runtime signals.

# SQL parameter style policy

Scenario SQL may use a human-friendly named style such as:
- `:price_list_id`

Scenario params may be provided separately as a JSON object.

Prefer keeping the SQL in the scenario readable and close to business intent.
Do not rewrite scenario SQL manually unless absolutely necessary.

If the execution tool supports adapting named parameters to the underlying database driver format, use that capability.
If the execution tool does not support the scenario's parameter style, report this as a tooling limitation instead of silently changing scenario semantics.

# Validation rules

Check as applicable:
- row exists / row count
- specific column values
- status fields
- foreign key relationships
- timestamps or audit rows if relevant
- consistency with scenario-defined expectations
- consistency with code-analysis findings only if code-analysis was actually used

# Status rules

Use the shared status model from `qa-entrypoint`. The mapping below clarifies how that model applies to DB verification.

- PASS — query executed and returned expected data
- FAIL — query executed but returned unexpected data
- BLOCKED — missing DB config/access, unresolved required variables, or disallowed query
- ERROR — tool/runtime/database failure

# Code analysis policy

Code-analysis is optional, not required for normal DB verification.

Use code-analysis only when:
- the expected persistence behavior is unclear
- the relevant table/entity is uncertain
- the query result contradicts the scenario expectation
- debugging requires implementation evidence

Do not inspect the codebase by default when the scenario already provides:
- explicit SQL
- explicit params
- explicit expected DB outcomes

# Guardrails

- Allow only read-only SELECT queries.
- Never mutate data.
- Never invent table names, columns, or relationships without saying so explicitly.
- If the SQL is ambiguous or not aligned with the scenario, say so clearly.
- If execution is blocked by a tooling limitation, say so clearly.
- Do not silently rewrite business expectations just to fit tool limitations.
- Do not append connection options such as SSL flags by mutating raw `DATABASE_URL` in ad hoc snippets. If DB connectivity is blocked, report the structured `tools/db/query_check.py` result or route the issue to env/tooling repair.

# Reporting expectations

Record:
- the executed DB step name
- the resolved SQL params
- row count
- relevant returned evidence
- whether expectations matched
- any assumptions or unresolved ambiguities
- any tooling issues or SQL compatibility workarounds

If a tool-level limitation affected execution, report it separately from the business validation result.

# Completion criteria

This skill is complete when the database verification step has:
- been executed or clearly marked BLOCKED/ERROR
- been validated against expectations
- produced evidence usable in the final report
- recorded any relevant assumptions or tooling limitations
