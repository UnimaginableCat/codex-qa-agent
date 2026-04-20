---
name: scenario-test-runner
description: Use this skill when the user asks to execute a markdown QA scenario against a local project under code/, with environment resolution, code analysis, API and DB verification, and a final report.
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
3. The target project under `code/<project-name>`

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
4. Use `code-analysis` first.
5. For each API step, use `api-workflow`.
6. For each DB validation step, use `db-verification`.
7. Use `reporting` to assemble the final report under `artifacts/agent/`.

# How to think about execution

For each step:
- identify the step type
- determine required inputs
- determine dependencies on previous steps
- validate expectations against actual outputs
- record evidence

Do not skip code analysis unless the user explicitly asks to skip it.

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
- Prefer evidence from code and tool outputs over assumptions.

# Completion criteria

This skill is complete only when:
- environment readiness was checked
- code analysis was done
- all executable steps were attempted
- statuses were assigned consistently
- a final report was produced