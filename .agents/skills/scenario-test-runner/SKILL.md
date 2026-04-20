---
name: scenario-test-runner
description: Use this skill when the user asks to execute a markdown QA scenario against a local project under code/, with environment resolution, API and DB verification, optional code analysis, and a final report.
---

# Purpose

This skill orchestrates end-to-end scenario execution for a target project inside `code/`.

Use this skill when:
- the user provides a scenario file
- the user wants to validate business functionality end-to-end
- the scenario includes API calls, DB checks, or both
- the user wants a final QA report

# Inputs to read first

1. The scenario file
2. `AGENTS.md`
3. The target project under `code/<project-name>` only if needed for clarification, debugging, or expectation validation

# Expected scenario structure

The scenario usually contains:
- project path
- goal
- environment file
- ordered steps
- expected outcomes

If the scenario is incomplete, do a best-effort run and clearly mark assumptions.

# Required execution order

1. Read and understand the scenario.
2. Identify the target project under `code/`.
3. Use `env-resolution` to validate execution readiness.
4. Execute API and DB steps directly from the scenario whenever the scenario is sufficiently explicit.
5. Use `code-analysis` only in the following cases:
   - the scenario is ambiguous
   - the expected behavior is unclear
   - an API/DB result contradicts expectations
   - additional evidence from code is needed for the final report
   - debugging is required after a FAIL / ERROR / unexpected response
6. For each API step, use `api-workflow`.
7. For each DB validation step, use `db-verification`.
8. Use `reporting` to assemble the final report under `artifacts/agent/`.

# How to think about execution

For each step:
- identify the step type
- determine required inputs
- determine dependencies on previous steps
- validate expectations against actual outputs
- record evidence

Prefer executing the scenario directly from its declared inputs and expectations.
Do not scan the codebase by default if the scenario already provides enough information to run.
Use code inspection only as a fallback or clarification mechanism.

# Code analysis policy

Code analysis is optional, not mandatory.

Use `code-analysis` only as a last resort when:
- the scenario does not clearly define the expected behavior
- the correct endpoint, field, table, or side effect is uncertain
- the environment behaves unexpectedly and root-cause hints are needed
- DB validation requires confirming how persistence should work
- the final report would be materially improved by code-backed evidence

Do not perform broad codebase scanning when the scenario already contains:
- explicit API paths
- request bodies
- expected response fields
- expected DB tables/queries
- clear success criteria

# Status model

Use these statuses consistently:
- PASS
- FAIL
- BLOCKED
- ERROR

# Guardrails

- Never expose secrets.
- Never run destructive DB queries.
- Never invent endpoints, tables, or fields without saying so explicitly.
- Prefer evidence from actual tool outputs over assumptions.
- Prefer scenario-defined expectations over unnecessary code exploration.
- If code analysis was skipped because the scenario was sufficiently explicit, say so briefly in the report.

# Completion criteria

This skill is complete only when:
- environment readiness was checked
- all executable API/DB steps were attempted
- code analysis was used only if needed
- statuses were assigned consistently
- a final report was produced