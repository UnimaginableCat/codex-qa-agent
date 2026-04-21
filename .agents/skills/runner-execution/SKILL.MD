---
name: runner-execution
description: Use this skill to execute a QA scenario through the local scenario runner, inspect the produced run artifacts, and return the final result. Prefer this skill over manual API/DB step execution when a runnable scenario file already exists.
---

# Purpose

This skill is the default entrypoint for scenario-based QA execution when a runnable scenario file already exists.

Use this skill when:
- the user asks to run a QA scenario
- a markdown scenario file already exists
- the local scenario runner is available
- the user wants an end-to-end result with artifacts, summary, and final report

Prefer this skill over manual step-by-step API/DB execution.

# When to use this skill

Use this skill first if:
- the scenario file is already written
- the runner CLI exists
- the user wants to validate a business flow end-to-end
- the expected output is a final scenario result, not a partial debug trace

Do not default to manual API and DB execution if the scenario can be run through the runner.

# Inputs to read first

1. `AGENTS.md`
2. the target scenario file
3. runner entrypoint location
4. optional existing run artifacts if this is a rerun or investigation

# Default execution policy

The runner is the primary execution mechanism.

Default flow:
1. Read the scenario.
2. Confirm the scenario path.
3. Identify the runner CLI command.
4. Execute the scenario through the runner.
5. Inspect produced artifacts:
   - `summary.json`
   - `report.md`
   - step artifacts if needed
6. Return the final outcome to the user.

# Required behavior

## 1. Prefer runner execution

If a valid scenario file exists, do this first:
- run the local scenario runner
- wait for completion
- inspect the generated artifacts
- summarize the result

Do not manually replay API and DB steps first.

## 2. Use manual investigation only as fallback

Use manual analysis, direct API execution, DB inspection, or code scanning only if:
- the runner cannot start
- the runner fails before scenario execution
- the runner output is incomplete or contradictory
- the user explicitly asks for step-by-step debugging
- deeper investigation is needed after FAIL / BLOCKED / ERROR

## 3. Treat the scenario as the source of truth

Use the scenario for:
- target project
- environment path
- ordered steps
- expected outcomes
- report location

Do not invent alternative endpoints, SQL, or expectations unless clearly marked as a debugging assumption.

# Execution workflow

1. Read the scenario file.
2. Resolve:
   - scenario name
   - target project
   - env path
   - report path if declared
3. Locate the runner command.
4. Execute the runner against the scenario.
5. Read the final outputs:
   - final status
   - summary
   - report
6. Return:
   - final status
   - short summary
   - key blockers/failures
   - exact artifact paths

# Expected artifacts to inspect

At minimum inspect:
- `.codex-qa/runs/<run-id>/summary.json`
- `artifacts/agent/<scenario-slug>-<run-id>/report.md`

If needed, also inspect:
- step input artifacts
- step result artifacts
- journal files
- preflight details

# Output format

Provide a concise factual result with:
- scenario name
- target project
- final status
- short explanation
- key failed/blocked steps if any
- exact paths to summary and report

# Status interpretation

Interpret runner output using these statuses:
- PASS
- FAIL
- BLOCKED
- ERROR

Do not override the runner’s final status unless you have strong evidence that the runner itself is incorrect.
If runner output and artifacts disagree, say so explicitly.

# Guardrails

- Never expose secrets.
- Never write new implementation code into `artifacts/`.
- Do not bypass the runner unless necessary.
- Do not manually execute destructive DB queries.
- Do not claim a scenario passed without checking runner output artifacts.
- Do not perform broad codebase scanning by default.

# Completion criteria

This skill is complete when:
- the runner was executed or a clear reason was given why it could not be executed
- final artifacts were inspected
- the user received the final status and artifact paths
- any fallback investigation was clearly marked as fallback/debug behavior