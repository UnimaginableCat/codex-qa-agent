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

# Python environment policy

Always prefer the workspace or project virtual environment for runner execution.

Required order:
1. first look for a local virtual environment
2. if a local venv interpreter exists, use it for all runner invocations
3. do not default to system `python` if a local venv is available
4. use system `python` only as a fallback when no suitable local venv exists
5. if system `python` is used, say so explicitly in the result
6. if runner preflight fails due to missing dependencies under system `python`, retry with local venv before deeper investigation

## Virtual environment discovery rules

Do not detect virtual environments with `rg --files`.

Always detect the interpreter by checking explicit executable paths first.

Search order:

### 1. workspace root
- `.venv/bin/python`
- `venv/bin/python`
- `.venv/Scripts/python.exe`
- `venv/Scripts/python.exe`

### 2. parent directory of the workspace
- `../.venv/bin/python`
- `../venv/bin/python`
- `../.venv/Scripts/python.exe`
- `../venv/Scripts/python.exe`

### 3. limited fallback search
Only if the explicit checks above fail, use a limited filesystem search.

Examples:
- `find . .. -maxdepth 3 \( -path '*/.venv/bin/python' -o -path '*/venv/bin/python' -o -path '*/.venv/Scripts/python.exe' -o -path '*/venv/Scripts/python.exe' \) -type f 2>/dev/null | head -n 1`

A hidden directory such as `.venv` must still be checked explicitly.

Do not conclude that no venv exists just because a generic file listing command returned nothing.

If both system Python and a local venv are available, always use the local venv.

Before reporting missing Python dependencies:
- confirm which interpreter was used
- confirm that explicit venv path checks were attempted
- retry with the discovered venv interpreter if one exists

A failed venv lookup is not valid unless explicit path checks were performed.

# Scenario variable resolution policy

Some scenario variables may come from the environment file rather than being written as literal values in the scenario.

When the scenario references variables, resolve them using this priority:

1. captured values from previous executed steps
2. explicit scenario-defined variables
3. environment-backed variables from the resolved env file
4. generated runtime variables
5. derived or template variables built from already resolved values

Environment-backed variables are allowed and expected.

Typical examples:
- `company_guid`
- `auth_login`
- `auth_password`
- `auth_token`
- base URLs
- service-specific identifiers

If a scenario variable is marked or described as coming from environment or config, try to resolve it from the env file before treating it as missing.

Do not assume that every variable must be declared literally inside the scenario body.

If a variable is not present in the scenario text but exists in the env file and is clearly relevant to execution, it may be used as the resolved value.

Examples:
- `company_guid` may come from `env/<project>.env`
- `auth_login` and `auth_password` may come from env for Basic Auth
- `run_suffix` may be generated at runtime
- `generated_price_list_name` may be derived from `AUTOTEST Attributes Flow {{run_suffix}}`

Never print raw secret values when reading variables from env.

# Default execution policy

The runner is the primary execution mechanism.

Default flow:
1. read the scenario
2. confirm the scenario path
3. identify the runner CLI command
4. resolve the Python interpreter, preferring local venv
5. load the env file and resolve initial variables
6. execute the scenario through the runner
7. inspect produced artifacts:
   - `summary.json`
   - `report.md`
   - step artifacts if needed
8. return the final outcome

# Required behavior

## 1. Prefer runner execution

If a valid scenario file exists, do this first:
- run the local scenario runner
- use the local venv interpreter if available
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

## 4. Treat interpreter selection as part of execution correctness

Interpreter selection is not a minor detail.

If the workspace has a local venv, runner execution through system `python` is considered an incorrect first attempt unless the user explicitly asked for that interpreter.

Before concluding that dependencies are missing or the runner is broken:
- verify whether a local venv exists
- retry with the local venv interpreter if available

## 5. Resolve scenario variables before step execution

Before running the scenario:
- load the resolved env file
- identify which scenario variables may be satisfied from env
- build initial runtime context from:
  - scenario variables
  - env-backed variables
  - generated variables
  - derived variables

Do not wait until Step 1 fails on an unresolved placeholder if the value can be resolved from env beforehand.

Do not mark a variable as missing until both the scenario-defined variables and the resolved env file were checked.

# Execution workflow

1. read the scenario file
2. resolve:
   - scenario name
   - target project
   - env path
   - report path if declared
3. determine the workspace root explicitly
4. run venv path checks relative to the workspace root
5. if needed, run secondary checks relative to the parent directory
6. locate the runner command
7. resolve the Python interpreter with this priority:
   - local venv python
   - system python fallback
8. load the env file
9. resolve initial variables from:
   - scenario-defined variables
   - env-backed values
   - generated runtime values
   - derived or template variables
10. execute the runner against the scenario
11. read the final outputs:
   - final status
   - summary
   - report
12. return:
   - final status
   - short summary
   - key blockers or failures
   - exact artifact paths
   - which Python interpreter was used

Do not rely only on the current shell directory if paths suggest a nested workspace.

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
- key failed or blocked steps if any
- exact paths to summary and report
- interpreter used for execution

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
- Do not report missing dependencies until you have checked whether a local venv exists.
- Do not treat a failed system-python attempt as conclusive if a local venv is available.
- Do not claim that no venv exists unless explicit path checks were performed.
- Do not mark a variable as unresolved until scenario variables and env-backed values were both checked.
- Do not print secrets loaded from env.

# Completion criteria

This skill is complete when:
- the runner was executed or a clear reason was given why it could not be executed
- the interpreter choice was explicit
- initial variable resolution was attempted from both scenario and env
- final artifacts were inspected
- the user received the final status and artifact paths
- any fallback investigation was clearly marked as fallback or debug behavior