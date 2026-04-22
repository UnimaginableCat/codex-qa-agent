---
name: reporting
description: Use this skill to assemble a final QA report from scenario execution results, optional code analysis, API execution, DB verification, assumptions, blockers, and raw evidence.
---

# Purpose

This skill standardizes the final QA report so results are consistent, evidence-based, and easy to read.

Use this skill when:
- multiple scenario steps have already been analyzed or executed
- a final user-facing QA result is needed
- evidence from API, DB, and optional code analysis must be consolidated
- blockers, failures, assumptions, variable resolutions, and tooling issues must be presented clearly

# Inputs to gather

Before writing the report, collect:
- target project path
- scenario path/name
- scenario file resolution details if the requested path did not match exactly
- run mode (`auto`, `guided`, or `manual`) if produced by the runner
- continuation state and run/step termination details if present
- operator state, pause-state path, decision point, selected action, and resume result if the run was guided/manual
- optional code-analysis summary
- API step results
- DB step results
- resolved variables used during execution
- resolved auth mode used during API execution
- assumptions made during execution
- blocker/error details
- tooling limitations or workarounds encountered
- paths to saved artifacts if any

# Reporting workflow

1. Identify the target project and scenario.
2. Treat runner-generated artifacts as evidence, not as files to mutate.
3. Review all step outcomes.
4. Determine the final overall legacy status without treating lifecycle labels as statuses.
5. Summarize the most important findings first.
6. Add lifecycle/termination context when available: completed, paused, resumed, aborted, skipped, partially completed, runtime failure, policy/config block.
7. Add operator context only when artifacts include a real `operator_state`, pause-state path, or decision point.
8. Add step-by-step results.
9. Add resolved variables, auth mode, assumptions, blockers, tooling issues, and evidence references.
10. Write a separate final report only when the runner did not already produce the required report or the user explicitly asks for a custom report.

# Final status rules

Determine one final status using the following priority:

1. ERROR
   - use when the run failed due to tool/runtime/parsing failures
2. BLOCKED
   - use when required setup, auth, config, environment, or dependencies were missing
3. FAIL
   - use when execution happened, but expectations were not met
4. PASS
   - use when all critical checks passed

If multiple statuses are present, use the highest-priority one from the list above.

Tooling issues must influence final status only when they actually prevented or invalidated execution.
Do not downgrade a legitimate business PASS unless the tooling issue materially affected confidence or correctness.

Keep these concepts separate:
- reporting status: legacy `PASS`, `FAIL`, `BLOCKED`, `ERROR`
- lifecycle/continuation: active, paused, resumed, terminal
- termination: completed, failed, blocked, errored, paused, skipped, aborted, partial completion
- operator resolution: selected action and resume strategy

# Required report structure

The report must include:

## 1. Header
- report title
- target project
- scenario
- final status

## 2. Executive summary
A short explanation of what was tested and what happened.

## 3. Scenario resolution
Include:
- requested scenario path or name
- actual scenario file used if different
- note whether a close-match filename resolution was used

If the scenario path matched exactly, say so briefly or omit this section if unnecessary.

## 4. Execution context
Include:
- target project
- environment file used
- run mode and continuation state if produced by the runner
- run termination reason/source if present
- pause-state path and active decision point if the run is paused
- selected operator action and resume strategy if the run was resumed
- resolved auth mode used for API execution, if relevant
- whether code-analysis was used or skipped

## 5. Resolved variables
List important resolved variables that influenced execution, for example:
- generated names
- IDs captured from prior steps
- env-derived values such as `company_guid`

Do not expose secrets.

## 6. Code analysis summary
Include this section only if code-analysis was actually used.
Summarize:
- probable code path
- expected side effects
- important risks or mismatches

## 7. Step results
For each step:
- step name or number
- type (API / DB / analysis / other)
- status
- termination kind/reason if available and materially different from status, for example `skipped` by operator
- short factual result
- key evidence

## 8. Blockers and failures
List anything that prevented full validation or caused incorrect behavior.

## 9. Assumptions
List all assumptions explicitly.

## 10. Tooling issues and workarounds
List:
- tool/runtime limitations encountered
- compatibility issues
- temporary workarounds used
- whether those issues affected final confidence

Keep this separate from business validation results.

## 11. Artifacts
List output files or raw evidence paths if they exist.

# Writing style

- Be concise, factual, and audit-friendly.
- Prefer evidence over interpretation.
- Avoid vague phrases like "seems fine" or "probably works".
- Make it easy for the user to understand what passed, failed, was blocked, or was affected by tooling.
- Clearly separate business validation from infrastructure or tooling issues.

# Guardrails

- Never expose secrets.
- Do not confuse runner lifecycle/termination semantics with legacy report statuses.
- Do not infer operator decisions from status alone; use decision resolution or operator state when available.
- Do not invent guided/manual interaction when the run is terminal and no pause-state or active decision point exists.
- Do not edit generated runner artifacts such as `report.md`, `summary.json`, `journal.jsonl`, `pause-state.json`, manifests, or raw step results unless the user explicitly asks to repair artifacts.
- Do not hide assumptions.
- Do not hide scenario path substitutions or variable resolutions that materially affected execution.
- Do not mark a scenario PASS if critical steps were BLOCKED, FAIL, or ERROR.
- Do not overstate confidence when evidence is incomplete.
- Do not present tooling workarounds as if they were part of the intended business flow.
- Do not include empty sections unless they add value.

# Completion criteria

This skill is complete when:
- all executed steps are reflected in the report
- the final status is consistent with the step outcomes
- assumptions, blockers, variable resolutions, and tooling issues are explicit
- optional code-analysis findings are included only if code-analysis was used
- the existing runner report is referenced, or a separate report is saved only when needed
