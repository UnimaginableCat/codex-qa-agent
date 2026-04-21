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

# Network and sandbox policy

Runner results must be interpreted in the context of the actual execution environment.

Before concluding that a scenario is blocked by the target system, first verify whether the current agent session itself has outbound DNS and HTTPS access from the same execution context that will run the scenario.

## When this check is required

Run the network precheck before rerunning the scenario if any of the following is true:
- previous runner output failed on DNS resolution
- previous runner output failed on connection setup before any HTTP response
- the session appears to be sandboxed or restricted
- the workspace config indicates sandboxed execution, such as `sandbox_mode = "workspace-write"`
- outbound network access may be unavailable or policy-restricted

## Required precheck context

The checks must run from the same interpreter and environment that will execute the runner:
- use the resolved local venv interpreter if available
- use the same working directory
- do not run the checks from a different shell, host, or interpreter and assume equivalence

## Required network checks

For the target API hostname, run:

1. Python DNS resolution:
   - `socket.gethostbyname(hostname)`
   - `socket.getaddrinfo(hostname, port)`

2. HTTPS probe with requests:
   - `requests.get(url, timeout=15, verify=False)`

3. System resolver check:
   - `getent hosts <hostname>`

4. Report execution context indicators:
   - whether sandbox/network access appears restricted
   - whether proxy variables are present
   - which interpreter path was used

## How to interpret the result

If DNS and HTTPS both fail from the same runner execution context, and the session is sandboxed or network-restricted, treat this as strong evidence that the BLOCKED result is caused by the agent environment rather than the target API itself.

In that case:
- do not over-diagnose the application
- do not claim the target host is definitively down
- say clearly that the runner result is explained by environment/network restriction in the current agent session
- say that a rerun from a context with outbound network access is required for a meaningful application-level result

If DNS works and HTTPS reaches the host, then continue with normal runner execution and interpret the runner result as a scenario/system outcome.

## Sandbox-specific rule

If the session indicates restricted network access, for example:
- sandboxed execution
- `sandbox_mode = "workspace-write"`
- explicit restricted network policy
- direct DNS/HTTPS probe failures from the runner interpreter

then do not present the runner BLOCKED status as evidence of an application bug unless there is additional proof from a non-restricted environment.

# Default execution policy

The runner is the primary execution mechanism.

Default flow:
1. read the scenario
2. confirm the scenario path
3. identify the runner CLI command
4. resolve the Python interpreter, preferring local venv
5. load the env file and resolve initial variables
6. if needed, run network/sandbox reachability precheck from the same execution context
7. execute the scenario through the runner
8. inspect produced artifacts:
   - `summary.json`
   - `report.md`
   - step artifacts if needed
9. return the final outcome

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

## 5. Treat agent network reachability as part of execution correctness

If the scenario depends on outbound API access, network reachability from the current session is part of execution correctness.

Before treating DNS or connection failures as application failures:
- verify DNS from the runner interpreter
- verify HTTPS connectivity from the runner interpreter
- verify whether the session is sandboxed or network-restricted

A runner result that is blocked by sandbox DNS failure is not a meaningful business-flow result.

# Execution workflow

1. Read the scenario file.
2. Resolve:
   - scenario name
   - target project
   - env path
   - report path if declared
3. Locate the runner command.
4. Resolve the Python interpreter with this priority:
   - local venv python
   - system python fallback
5. Load env-backed variables and generated runtime variables.
6. If previous evidence suggests connectivity issues, run DNS/HTTPS precheck from the same execution context.
7. Execute the runner against the scenario.
8. Read the final outputs:
   - final status
   - summary
   - report
9. Return:
   - final status
   - short summary
   - key blockers/failures
   - exact artifact paths
   - which Python interpreter was used
   - whether network access was verified
   - whether the result may be explained by sandbox restrictions

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
- interpreter used for execution
- whether DNS worked
- whether HTTPS worked
- whether outbound network appears restricted
- whether that explains the runner result

# Status interpretation

Interpret runner output using these statuses:
- PASS
- FAIL
- BLOCKED
- ERROR

Do not override the runner’s final status unless you have strong evidence that the runner itself is incorrect.
If runner output and artifacts disagree, say so explicitly.

If the runner says BLOCKED because of DNS/connectivity failure and the same failure is reproducible from the agent execution context, report that the scenario is BLOCKED in this environment and that the result is environment-constrained.

# Guardrails

- Never expose secrets.
- Never write new implementation code into `artifacts/`.
- Do not bypass the runner unless necessary.
- Do not manually execute destructive DB queries.
- Do not claim a scenario passed without checking runner output artifacts.
- Do not perform broad codebase scanning by default.
- Do not claim the target API is broken when the current agent session has restricted network access.
- Do not treat repr-style quotes in diagnostics as proof that real URL values contain quotes; compare raw value and normalized value separately.