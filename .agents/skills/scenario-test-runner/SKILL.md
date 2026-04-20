---
name: scenario-test-runner
description: Use this skill when the user asks to execute a markdown QA scenario against a local project under code/, with environment resolution, API and DB verification, minimal code inspection, and a final report.
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

# Scenario discovery

If the user-provided scenario path does not exist exactly:
1. Look for a close match in the expected scenario directory.
2. Prefer obvious filename variants:
   - kebab-case
   - snake_case
   - same feature name with small naming differences
3. If exactly one clear candidate is found, use it and record that resolution in the final report.
4. If multiple plausible candidates are found, stop and mark the run as `BLOCKED`.

Do not guess silently when multiple scenario files could match.

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
4. Resolve scenario variables from explicit scenario content and environment values when possible.
5. Execute API and DB steps directly from the scenario whenever the scenario is sufficiently explicit.
6. Use `code-analysis` only in narrowly justified cases.
7. For each API step, use `api-workflow`.
8. For each DB validation step, use `db-verification`.
9. Use `reporting` to assemble the final report under `artifacts/agent/`.

# Variable resolution policy

Before step execution, resolve variables from the most explicit available source in this order:
1. values explicitly declared in the scenario
2. values captured from previous steps
3. environment values from the resolved env file
4. generated runtime values explicitly requested by the scenario, for example timestamps or unique names

Examples:
- `{{generated_price_list_name}}` may be generated at runtime if the scenario explicitly asks for it
- `{{company_guid}}` may be resolved from `COMPANY_GUID` in env if the scenario does not provide another source
- auth credentials should come from env/config when the scenario says so

Record important variable resolutions briefly in the final report.

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
- an API/DB result contradicts expectations
- the environment behaves unexpectedly and root-cause hints are needed
- DB validation requires confirming how persistence should work
- the final report would be materially improved by code-backed evidence

Do not perform broad codebase scanning when the scenario already contains:
- explicit API paths
- request bodies
- expected response fields
- expected DB tables/queries
- clear success criteria

If code-analysis is used, keep it narrow and targeted to the exact ambiguity or failure.

# Tooling modification policy

Do not modify `tools/`, `skills/`, scenario files, or shared execution infrastructure during a normal scenario run.

If a tooling problem is encountered:
- prefer reporting it as a tooling issue
- mark the affected step as `ERROR` or `BLOCKED` as appropriate
- describe the minimal suspected fix in the final report if useful

Modify tooling only if the user explicitly asked to debug or repair the tooling itself.

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
- If scenario execution required assumptions, state them explicitly.
- If scenario file resolution used a close filename match, state that explicitly.
- If tooling limitations affected execution, state that explicitly.

# Reporting expectations

The final report should clearly separate:
- scenario execution results
- resolved assumptions and variables
- tooling issues or workarounds
- optional code-analysis findings, if code-analysis was used

Do not mix tooling problems with business validation results without saying so explicitly.

# Completion criteria

This skill is complete only when:
- environment readiness was checked
- scenario variables were resolved as far as possible
- all executable API/DB steps were attempted
- code analysis was used only if needed
- statuses were assigned consistently
- a final report was produced