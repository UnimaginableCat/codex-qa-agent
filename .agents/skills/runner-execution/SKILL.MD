---
name: runner-execution
description: Use this skill to execute QA scenarios through the local scenario runner in auto or guided/manual mode, inspect produced artifacts, handle pause/decision/resume workflows, and return the final result. Prefer this skill over ad hoc API/DB step execution when a runnable scenario file exists.
---

# Purpose

This skill is the default entrypoint for scenario-based QA execution when a runnable scenario file already exists.

Use this skill when:
- the user asks to run a QA scenario
- a markdown scenario file already exists
- the local scenario runner is available
- the user wants an end-to-end result with artifacts, summary, and final report
- the user asks for guided/manual execution, pending decision inspection, or resume from a pause state

Prefer this skill over ad hoc step-by-step API/DB execution.

# Current runner model

The runner has separate responsibilities:
- engine: execution semantics, lifecycle, outcomes, pause/resume, operator decisions, and termination
- projections: summary/report/operator-facing read models
- persistence: run state, pause state, journal, summary, reports, and step artifacts
- CLI: thin adapter over service/use-case contracts, not the source of orchestration truth

Use explicit run modes:
- `auto`: default legacy mode; CLI output is the compatibility summary payload
- `guided`: operator-facing mode; CLI output includes `summary` plus `operator_state`
- `manual`: explicit operator/manual workflow mode; treat like guided unless code provides narrower behavior

# When to use this skill

Use this skill first if:
- the scenario file is already written
- the runner CLI exists
- the user wants to validate a business flow end-to-end
- the expected output is a final scenario result, a guided pause/decision payload, or a resumed run result

Do not default to ad hoc API and DB execution if the scenario can be run through the runner.

# Inputs to read first

1. `AGENTS.md`
2. the target scenario file
3. runner entrypoint location
4. optional existing run artifacts if this is a rerun or investigation

# Python environment policy

Use a Python interpreter that satisfies the workspace runtime guard. This workspace requires Python 3.14+.

Required order:
1. first look for a local virtual environment
2. verify the interpreter version before using it
3. use the local venv only if it satisfies Python 3.14+
4. if the local venv is older, use a compatible system launcher such as `py` on Windows and say so explicitly
5. do not report runner/CLI failure from an unsupported interpreter as a product or scenario result
6. if runner preflight fails due to missing dependencies under a fallback interpreter, retry with a compatible local venv only if one exists

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

If both system Python and a local venv are available, prefer the local venv only when it satisfies the runner's Python version requirement.

Before reporting missing Python dependencies:
- confirm which interpreter was used
- confirm that explicit venv path checks were attempted
- retry with the discovered venv interpreter only if it is compatible

A failed venv lookup is not valid unless explicit path checks were performed.

# Scenario variable resolution policy

Some scenario variables may come from the environment file rather than being written as literal values in the scenario.

Variables must be machine-readable. Do not put prose instructions in a variable value. The runner does not infer human intent from text such as "the lowercase form of `run_suffix`"; that is an invalid scenario definition and must block before API/DB execution.

Supported explicit formats:
- `name = env:ENV_NAME`
- `name = generated:run_suffix`
- `name = generated:run_id`
- `name = generated:timestamp_suffix`
- `name = generated:uuid`
- `name = template:AUTOTEST {{run_suffix}}`
- `name = derived:run_suffix|lower`
- `name = derived:raw_name|trim|upper`
- `name = literal:Fixed literal`

Supported transforms for `derived` variables:
- `lower`
- `upper`
- `trim`

Good definitions:
- `email_suffix = derived:run_suffix|lower`
- `primary_email = template:autotest.primary.{{email_suffix}}@example.com`
- `missing_user_id = generated:uuid`

Bad definitions:
- `email_suffix = the lowercase form of `run_suffix``
- `run_suffix generated dynamically`
- `generated_name derived from run suffix`
- `static_label = Fixed literal without literal prefix`

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
- use the resolved Python 3.14+ runner interpreter
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

# Runner modes and commands

The runner is the primary execution mechanism.

Use the CLI as an adapter over service contracts:
- auto run: `python -m tools.scenario_runner.cli --scenario <scenario.md>`
- guided run: `python -m tools.scenario_runner.cli --scenario <scenario.md> --mode guided`
- inspect active decision: `python -m tools.scenario_runner.cli --inspect-pause <pause-state.json>`
- resume with operator action: `python -m tools.scenario_runner.cli --resume <pause-state.json> --action <action_id>`

In guided mode, inspect the `operator_state` payload. It should include:
- `run_id`
- `run_mode`
- `continuation_state`
- `final_status`
- `resumable`
- `pause_state_path`
- `active_decision_point`
- `available_actions`
- `recommended_action_id`
- `required_inputs`
- `resume_instructions`
- `run_termination`

When `operator_state.resumable` is true, do not invent a resolution. Present or select one of `available_actions[].action_id` according to the user's instruction. If the user did not choose an action, report the pending decision and stop.

# Default execution policy

Default flow:
1. read the scenario
2. confirm the scenario path
3. identify the runner CLI command
4. resolve a Python 3.14+ interpreter
5. load the env file and resolve initial variables
6. if needed, run network/sandbox reachability precheck from the same execution context
7. execute the scenario through the runner in `auto` unless guided/manual behavior was requested
8. for guided/manual mode, inspect `operator_state`, pending decision, and available actions
9. if the user selected an action, resume through `--resume ... --action ...`
10. inspect produced artifacts:
   - `summary.json`
   - `report.md`
   - `pause-state.json` if paused/resumed
   - step artifacts if needed
11. return the final outcome or pending operator decision

# Required behavior

## 1. Prefer runner execution

If a valid scenario file exists, do this first:
- run the local scenario runner
- use a Python 3.14+ interpreter
- wait for completion or guided pause
- inspect the generated artifacts
- summarize the result

Do not manually replay API and DB steps first.

## 2. Use ad hoc investigation only as fallback

Use ad hoc analysis, direct API execution, DB inspection, or code scanning only if:
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

If the workspace has a local venv that satisfies Python 3.14+, runner execution through system `python` is considered an incorrect first attempt unless the user explicitly asked for that interpreter.

If the local venv is older than Python 3.14, do not use it for runner CLI checks. Use a compatible interpreter such as `py` on Windows and mention the reason.

Before concluding that dependencies are missing or the runner is broken:
- verify whether a local venv exists
- retry with the local venv interpreter only if it is compatible

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
   - compatible local venv Python 3.14+
   - compatible system launcher fallback
5. Load env-backed variables and generated runtime variables.
6. If previous evidence suggests connectivity issues, run DNS/HTTPS precheck from the same execution context.
7. Execute the runner against the scenario in the requested run mode.
8. If guided/manual output includes `operator_state.resumable=true`, inspect and report the active decision point and available actions.
9. If the user selected an action, resume through the CLI resume command.
10. Read the final outputs:
   - final status
   - summary
   - report
   - operator state if guided/manual
11. Return:
   - final status
   - short summary
   - key blockers/failures
   - current continuation/termination state
   - pending decision and actions if paused
   - exact artifact paths
   - which Python interpreter was used
   - whether network access was verified
   - whether the result may be explained by sandbox restrictions

# Expected artifacts to inspect

At minimum inspect:
- `.codex-qa/runs/<run-id>/summary.json`
- `artifacts/agent/<scenario-slug>-<run-id>/report.md`

If needed, also inspect:
- `.codex-qa/runs/<run-id>/pause-state.json`
- step input artifacts
- step result artifacts
- journal files
- preflight details

# Output format

Provide a concise factual result with:
- scenario name
- target project
- final status
- run mode
- continuation state and run termination kind/reason when available
- short explanation
- key failed/blocked steps if any
- active decision point and available actions if paused
- exact paths to summary and report
- pause-state path if resumable or resumed
- interpreter used for execution
- whether DNS worked
- whether HTTPS worked
- whether outbound network appears restricted
- whether that explains the runner result

# Status interpretation

Do not confuse legacy status with lifecycle or termination. Use `continuation_state`, `run_termination`, and `operator_state` to explain whether the run completed, paused, resumed, was aborted, or stopped after partial completion.

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
- Do not duplicate pause/resume/operator decision logic outside the runner service/CLI contracts.
- Do not manually execute destructive DB queries.
- Do not claim a scenario passed without checking runner output artifacts.
- Do not perform broad codebase scanning by default.
- Do not claim the target API is broken when the current agent session has restricted network access.
- Do not treat repr-style quotes in diagnostics as proof that real URL values contain quotes; compare raw value and normalized value separately.
