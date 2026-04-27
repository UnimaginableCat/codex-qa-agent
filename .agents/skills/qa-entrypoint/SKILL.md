---
name: qa-entrypoint
description: Use this skill as the single entry point for work in the local codex-qa-agent workspace. It decides whether the request should follow scenario execution, targeted investigation, final reporting, or test-plan generation, and then routes to the appropriate specialized skills.
---

# Purpose

This skill is the top-level router for the workspace skill tree.

Use it first when the user request is broad, ambiguous, or expressed in workspace terms such as:
- run or validate a scenario
- inspect a failed run
- explain which skill flow to use
- generate a test plan
- decompose coverage into authoring DSL
- compile or promote generated plan artifacts
- investigate env, API, DB, or reporting issues without naming the exact skill

Do not treat this skill as a replacement for the specialized skills. Its job is to choose the right path and keep the sequence consistent.

# Workspace-wide instructions

Apply these rules across all QA branches unless a specialized skill adds a narrower requirement.

## Shared execution flow

For scenario-based QA, use this default order:

1. read the scenario carefully
2. identify the target project under `code/`
3. resolve execution readiness
4. use `runner-execution` first for runnable scenarios
5. read runner artifacts when they exist
6. use targeted follow-up only when the runner result or the user requires it
7. consolidate outcome and evidence

Prefer one dominant branch. Do not blend runner execution, broad code analysis, manual API replay, and DB checks unless the chosen branch actually requires them.

## Shared classification rules

Use one common reporting status model everywhere:

- `PASS`: the step executed and matched expectations
- `FAIL`: the step executed, but expectations were not met
- `BLOCKED`: execution could not proceed because of missing env, config, auth, access, dependency, or another setup problem
- `ERROR`: tool, runtime, parsing, or other technical failure prevented valid execution

Final status priority:

1. `ERROR`
2. `BLOCKED`
3. `FAIL`
4. `PASS`

Do not treat env/auth/config/access problems as product failures. Do not mark a scenario or step `PASS` if critical checks were `BLOCKED`, `FAIL`, or `ERROR`.

Keep reporting status separate from lifecycle labels such as `active`, `paused`, `resumed`, or `terminal`, and from termination semantics such as `completed`, `failed`, `blocked`, `errored`, `skipped`, or `aborted`.

## Shared evidence and safety rules

- Never expose secrets, tokens, passwords, connection strings, or raw credentials.
- Treat runner-generated artifacts as evidence. Do not edit `report.md`, `summary.json`, `journal.jsonl`, `pause-state.json`, manifests, or raw step results unless the user explicitly asks for artifact repair.
- Keep DB verification read-only.
- Do not invent endpoints, tables, columns, response fields, or business behavior without saying that it is an assumption.
- Keep assumptions explicit when evidence is incomplete.

## Shared scenario rules

- Prefer the project/workspace venv before falling back to other interpreters. If tooling/env readiness is missing and blocks execution, classify that as `BLOCKED`.
- For runnable scenarios, do not start with broad code analysis by default. Use the runner first, then inspect code only if the result or the user requires it.
- Manual API or DB execution is fallback work unless the user explicitly asked for that path or the runner cannot execute the required check.
- Scenario variable definitions must stay machine-readable. Do not treat prose descriptions as valid variable values when the DSL requires `env:`, `generated:`, `template:`, `derived:`, or `literal:`.

# Default routing

Choose one primary branch first:

1. Scenario execution branch
   Use when the request targets a runnable scenario under `scenarios/` or asks to execute, validate, resume, inspect, debug, or report a scenario run.
   Primary skill: `runner-execution`

2. Authoring branch
   Use when the request is about coverage decomposition, feature breakdown, controller CRUD coverage, workflow coverage design, or writing the compact authoring DSL.
   Primary skill: `agent-plan-authoring`

3. Downstream generation branch
   Use when the desired output is a compiled `agent-plan.json`, `NormalizedTestPlan`, rendered drafts, review output, promoted scenarios, or generation diagnostics from existing authored input.
   Primary skill: `test-plan-generation`

4. Focused investigation branch
   Use only when the user explicitly asks for a narrow investigation or when runner artifacts show a real need for deeper inspection.
   Primary skill depends on the question:
   - `env-resolution` for env/config/auth readiness
   - `code-analysis` for implementation tracing
   - `api-workflow` for manual HTTP execution
   - `db-verification` for read-only persistence checks

5. Final synthesis branch
   Use when execution/investigation already happened and the main remaining task is consolidating outcome and evidence.
   Primary skill: `reporting`

# Scenario-first policy

For runnable scenarios, the normal path is:

1. read scenario
2. identify target project under `code/`
3. execute through `runner-execution`
4. read runner artifacts
5. use `code-analysis`, `api-workflow`, or `db-verification` only if the runner result or the user requires it
6. assemble the result through `reporting` when needed

Do not start with broad code analysis for a runnable scenario unless the user explicitly asked for analysis or runner startup is blocked by a narrow ambiguity.

# Skill selection rules

- Prefer one primary skill for the main branch and add secondary skills only when the branch requires them.
- Prefer `runner-execution` over manual API/DB replay when a runnable scenario exists.
- Prefer `agent-plan-authoring` when the request is about decomposition, coverage design, or writing `authoring-plan.yaml`.
- Prefer `test-plan-generation` when the request starts from existing authored input and asks for compile, generate, render, review, promote, or validate.
- Do not route broad coverage-authoring requests directly into `test-plan-generation`.
- Use `env-resolution` before manual API or DB work if config is unclear.
- Use `reporting` after execution/investigation when the user needs a final QA report or consolidated result.

# Output expectation

When this skill is used, the agent should make the routing decision explicit:
- target project if known
- chosen primary branch
- chosen primary skill
- authoring artifact when relevant: `authoring-plan.yaml`
- downstream artifact when relevant: compiled `agent-plan.json`
- secondary skills that may be needed later
- reason this branch was selected

# Invocation Pattern

Use a short, consistent request envelope:

```text
Use skill: qa-entrypoint

project: code/<project-name>
request: <what needs to be done>
```

This is the canonical team-facing entry point. Prefer this format unless there is a deliberate need
to bypass routing and invoke a specialized skill directly.

Examples:

```text
Use skill: qa-entrypoint

project: code/LeadFlow
request: Сгенерируй authoring-plan.yaml для полного покрытия InternalUserController.
```

```text
Use skill: qa-entrypoint

project: code/LeadFlow
request: Возьми существующий authoring-plan.yaml и запусти downstream generation до draft scenarios.
```

# Guardrails

- Do not invent a hybrid flow when one primary branch is clearly dominant.
- Do not bypass `runner-execution` for runnable scenarios without saying why.
- Do not use API or DB fallback first when the runner can provide the same evidence.
- Do not expand into multi-skill work without a concrete reason.
- Do not send coverage-authoring requests straight to downstream generation when `agent-plan-authoring` is the correct first step.

# Completion criteria

This skill is complete when:
- the workspace request has been classified into the correct branch
- the correct primary skill has been selected
- any necessary secondary skills are identified
- the next action in the chosen flow is clear
