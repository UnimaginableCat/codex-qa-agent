---
name: reporting
description: Use this skill to assemble a final QA report from code analysis, API execution, DB verification, assumptions, blockers, and raw evidence.
---

# Purpose

This skill standardizes the final QA report so results are consistent, evidence-based, and easy to read.

Use this skill when:
- multiple scenario steps have already been analyzed or executed
- a final user-facing QA result is needed
- evidence from API, DB, and code analysis must be consolidated
- blockers, failures, and assumptions must be presented clearly

# Inputs to gather

Before writing the report, collect:
- target project path
- scenario path/name
- code-analysis summary
- API step results
- DB step results
- assumptions made during execution
- blocker/error details
- paths to saved artifacts if any

# Reporting workflow

1. Identify the target project and scenario.
2. Review all step outcomes.
3. Determine the final overall status.
4. Summarize the most important findings first.
5. Add step-by-step results.
6. Add blockers, assumptions, and evidence references.
7. Write the final report to the expected location.

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

# Required report structure

The report must include:

## 1. Header
- report title
- target project
- scenario
- final status

## 2. Executive summary
A short explanation of what was tested and what happened.

## 3. Code analysis summary
- probable code path
- expected side effects
- important risks or mismatches

## 4. Step results
For each step:
- step name or number
- type (API / DB / analysis / other)
- status
- short factual result
- key evidence

## 5. Blockers and failures
List anything that prevented full validation or caused incorrect behavior.

## 6. Assumptions
List all assumptions explicitly.

## 7. Artifacts
List output files or raw evidence paths if they exist.

# Writing style

- Be concise, factual, and audit-friendly.
- Prefer evidence over interpretation.
- Avoid vague phrases like "seems fine" or "probably works".
- Make it easy for the user to understand what passed, failed, or was blocked.

# Guardrails

- Never expose secrets.
- Do not hide assumptions.
- Do not mark a scenario PASS if critical steps were BLOCKED, FAIL, or ERROR.
- Do not overstate confidence when evidence is incomplete.

# Completion criteria

This skill is complete when:
- all executed steps are reflected in the report
- the final status is consistent with the step outcomes
- assumptions and blockers are explicit
- the report is saved to the expected path