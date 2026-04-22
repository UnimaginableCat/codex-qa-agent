# AGENTS.md

## Workspace purpose

This workspace is used for scenario-based QA automation across multiple local projects placed under `code/`.

The workspace contains:
- local projects under `code/`
- reusable skills under `.agents/skills/`
- deterministic helper tools under `tools/`
- scenario definitions under `scenarios/`
- execution artifacts and reports under `artifacts/agent/`
- per-project environment files under `env/`

`scenario_runner` is the primary orchestration path for runnable scenarios. Treat its CLI as an adapter over runner services, not as the source of orchestration semantics. Engine state, pause/resume, operator decisions, termination semantics, projections, persistence, and reporting must remain distinct.

## Core operating model

The agent must treat this workspace as a QA execution environment.

Each scenario should be handled as:
1. scenario understanding
2. environment resolution
3. code analysis
4. API execution if needed
5. DB verification if needed
6. final reporting

When a scenario is runnable through `scenario_runner`, prefer runner execution over ad hoc API/DB replay. Use `auto` mode for ordinary execution and guided/manual mode when an operator decision, pause-state inspection, or explicit resume is needed.

The goal is not only to execute steps, but to verify the intended functionality against actual implementation and persisted system state.

## Required flow

1. Read the selected scenario carefully.
2. Identify the target project under `code/<project-name>`.
3. Resolve environment readiness and required configuration.
4. Analyze the relevant code path before executing runtime checks.
5. Execute API steps if needed.
6. Execute DB verification if needed.
7. Produce a final report under `artifacts/agent/`.

## Scenario Variables DSL

`## Variables` entries must be machine-readable. The runner must fail fast during validation if a variable value is ambiguous prose or uses an unsupported transform.

Supported formats:
- `name = env:ENV_NAME`
- `name = generated:run_suffix`
- `name = generated:run_id`
- `name = generated:timestamp_suffix`
- `name = generated:uuid`
- `name = template:prefix-{{run_suffix}}`
- `name = derived:source_variable|lower`
- `name = derived:source_variable|trim|upper`
- `name = literal:Fixed literal`

Supported derived transforms are `lower`, `upper`, and `trim`.

Good:
- `email_suffix = derived:run_suffix|lower`
- `primary_email = template:autotest.primary.{{email_suffix}}@example.com`

Bad:
- `email_suffix = the lowercase form of run_suffix`
- `run_suffix generated dynamically`
- `display_name = Fixed literal without literal prefix`

## Project awareness rules

- Always explicitly mention which project under `code/` is being analyzed.
- Prefer evidence from the target project's code over assumptions.
- If multiple projects are present, never assume the target project without checking the scenario.
- If the scenario is ambiguous, make the smallest reasonable assumption and state it clearly in the final report.

## Status model

Use the following statuses consistently:

- PASS — the step executed and matched expectations
- FAIL — the step executed, but expectations were not met
- BLOCKED — the step could not be executed because of missing config, missing access, missing env, auth issues, unavailable dependency, or other setup problem
- ERROR — tool/runtime/parsing/unexpected technical failure during execution

Priority of final scenario status:
1. ERROR
2. BLOCKED
3. FAIL
4. PASS

If multiple outcomes exist, the final scenario status must use the highest-priority status from the list above.

Do not use legacy statuses as lifecycle labels. For runner artifacts, distinguish:
- lifecycle/continuation state such as active, paused, resumed, terminal
- termination semantics such as completed, failed, blocked, errored, skipped, aborted, partially completed
- operator resolution such as selected action and resume strategy
- reporting status such as PASS, FAIL, BLOCKED, ERROR

## Rules

- Never print secrets.
- Never expose tokens, passwords, connection strings, or raw credentials in reports.
- Treat environment issues as BLOCKED, not FAIL.
- Treat auth/config/setup issues as BLOCKED, not FAIL.
- Treat assertion mismatches as FAIL.
- Treat tool/runtime crashes as ERROR.
- DB verification must be read-only.
- Never execute destructive or mutating SQL as part of verification.
- Never invent endpoints, DB tables, columns, or business behavior without saying that it is an assumption.
- Prefer code evidence and tool outputs over intuition.

## Expected evidence sources

The agent may use:
- scenario content
- project code under `code/`
- deterministic helper tools under `tools/`
- prior outputs produced during the current scenario run
- environment metadata from `env/`

The agent should ground conclusions in:
- code paths
- API responses
- DB query outputs
- explicit scenario expectations

## Reporting requirements

The final report must include:
- target project
- scenario name/path
- final status
- concise execution summary
- code analysis summary
- step-by-step outcomes
- blockers and failures
- assumptions
- artifact references if any

## Guardrails

- Do not silently skip critical steps.
- Do not mark a scenario PASS if critical steps were BLOCKED, FAIL, or ERROR.
- Do not interpret missing infrastructure as product failure.
- Do not overstate confidence when evidence is incomplete.
- If the system behavior cannot be confirmed, state that clearly.

## Skill usage policy

Prefer using the dedicated skills:

- `runner-execution` for scenario runner orchestration, auto/guided execution, pause inspection, and resume
- `env-resolution` for env/config readiness
- `code-analysis` for implementation tracing
- `api-workflow` for HTTP/API steps
- `db-verification` for read-only DB checks
- `reporting` for final QA report assembly

## Completion criteria

A scenario run is complete only when:
- the scenario was read
- the target project was identified
- environment readiness was checked
- code analysis was performed
- all executable runtime checks were attempted
- statuses were assigned consistently
- the final report was written, or a guided/manual pause with operator-facing next actions was reported
