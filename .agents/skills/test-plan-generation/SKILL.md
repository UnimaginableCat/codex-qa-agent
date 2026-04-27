---
name: test-plan-generation
description: Consume existing authoring DSL or compiled plan input in the local codex-qa-agent workspace and produce a typed NormalizedTestPlan plus downstream generation artifacts. Use when the request starts after authoring and the goal is compile, generate, render, review, promote, or validate rather than scenario_runner execution.
---

# Purpose

Use this skill as the downstream pipeline after authoring is already done.

Prefer compiled structured input over prose normalization. Direct `agent_plan` remains the low-level
escape hatch. Compact authoring belongs to the separate `agent-plan-authoring` skill.

If the user is asking to decompose coverage, write a new test plan from scratch, or "generate a test
plan" without an existing authoring artifact, route back through `qa-entrypoint` to
`agent-plan-authoring` first.

The canonical output remains `NormalizedTestPlan`. Optional downstream stages are:

- `render`
- `review`
- `promote`
- `validate`

Lifecycle:

```text
authored input -> compile -> normalized plan -> drafts -> review -> promoted scenarios -> validation
```

# Invocation

The normal user-facing entry point is `qa-entrypoint`.

Call this skill directly only when authored input already exists and the request should start inside
the downstream generation branch rather than being classified first.

# Operating Modes

- `compile`: compile `authoring-plan.yaml` into managed `agent-plan.json`.
- `generate`: accept compiled input, validate it, and produce `normalized-plan.json`.
- `render`: render markdown draft scenarios from the generated plan.
- `review`: inspect rendered drafts and classify promotion readiness.
- `promote`: promote selected or all reviewed drafts into `scenarios/generated`.
- `validate`: validate promoted scenario markdown after editing or readiness checks.

Use the minimum mode that satisfies the request. Stop at `NormalizedTestPlan` unless the user asked
for later phases.

# Core Commands

- Validate compiled plan:
  `<venv-python> -m tools.generation.cli --validate-agent-plan --agent-plan-file <bundle>/agent-plan.json --output-format text`
- Validate authoring DSL:
  `<venv-python> -m tools.generation.cli --validate-authoring-plan --authoring-plan-file <file> --output-format text`
- Compile authoring DSL:
  `<venv-python> -m tools.generation.cli --compile-authoring-plan --authoring-plan-file <file> --output artifacts/agent/generation --output-format text`
- Generate from structured plan:
  `<venv-python> -m tools.generation.cli --agent-plan-file <bundle>/agent-plan.json --workspace-root .`
- Generate from authoring DSL:
  `<venv-python> -m tools.generation.cli --authoring-plan-file <file> --workspace-root .`
- Prose fallback:
  `<venv-python> -m tools.generation.cli --source-id <id> --project code/<project> --prose "<text>" --workspace-root .`
- Render drafts:
  `<venv-python> -m tools.generation.cli --agent-plan-file <bundle>/agent-plan.json --workspace-root . --render-drafts`
- Review drafts:
  `<venv-python> -m tools.generation.cli --review-drafts --run-id <generation-run-id> --workspace-root .`
- Promote one:
  `<venv-python> -m tools.generation.cli --promote-draft --run-id <generation-run-id> --draft-id <draft-id> --workspace-root . --target-dir scenarios/generated`
- Promote all:
  `<venv-python> -m tools.generation.cli --promote-all-drafts --run-id <generation-run-id> --workspace-root . --target-dir scenarios/generated`
- Validate scenario:
  `<venv-python> -m tools.generation.cli --validate-scenario --path scenarios/generated/<file>.md --output-format text`

# Default Decisions

- Use compiled input unless the request is too vague or the user explicitly wants prose bootstrap.
- Expect `authoring-plan.yaml` or compiled `agent-plan.json` as the normal input.
- Route decomposition-first requests back to `agent-plan-authoring`.
- Validate authoring or compiled input before generation when the agent edited source artifacts.
- Stop at `NormalizedTestPlan` unless the user asked for downstream phases.
- When the user asks for scenario markdown previews, stop after `render`.
- When the user asks for real scenario files, continue through `review` and then `promote`.
- When the user asks to convert the whole rendered set, prefer `--promote-all-drafts` over shell loops.
- When the user asks only for validation/readiness, do not re-generate unless required artifacts are missing.

# Downstream Guidance

- Treat this skill as a consumer of authored input, not as a coverage-design skill.
- Preserve author intent while compiling and generating; do not add or expand cases unless the user explicitly asks for that rewrite.
- Treat `expected_outcomes[]`, `capture`, `workflow_steps[]`, and `db_verification` as executable downstream contracts.
- Treat rendered `actor = literal:<value>` as an execution profile selector for actor-scoped API/DB env keys, not as decorative notes-only metadata.
- If compile, render, or review reveals authoring defects, send the workflow back to `authoring-plan.yaml` rather than compensating by inventing new coverage here.
- Use direct `agent_plan` editing only as a low-level escape hatch for debugging or explicit manual control.

## Quality Gates

- `validate-agent-plan` is the minimum gate, not the only gate.
- `validate-authoring-plan` is the minimum gate for `authoring-plan.yaml` before compile.
- If later phases are requested, treat render/review/compile warnings as authoring defects to fix back in `authoring-plan.yaml` or compiled `agent-plan.json`, not as acceptable follow-up manual cleanup.
- Do not treat drafts with unresolved `data_setup`, `assertion_detail`, `environment`, `auth_strategy`, or `executable_detail` gaps as close to runnable or promotable. Return to the source authoring artifact instead.
- If a rendered standalone case still depends on seeded IDs, missing machine-readable variables, or undeclared setup fixtures, rewrite it as a self-contained workflow case or keep it deferred on purpose.

# Short Examples

- Bad: `GET /users/{{user_id}}` with unresolved note "seeded user_id must be supplied."
- Good: create the user in `workflow_steps[]`, capture `user_id`, then call `GET /users/{{user_id}}`.
- Bad: objective claims filter behavior, but assertions only check `HTTP 200` and `response JSON is an array`.
- Good: set up a matching entity first, then assert the collection proves the expected filter result deterministically.

# Rendering Rule

Draft rendering is authored-route-first:

- single-endpoint API cases should define `route`
- workflow cases should define complete `workflow_steps[]`
- rendering should not invent missing route, auth, payload, or DB details
- if render/review shows missing assertions, captures, or DB checks for a case intended for execution, return to the source authoring artifact and fix it before promotion
- drafts with execution-blocking typed gaps should remain deferred rather than being treated as acceptable preview candidates for promotion

# Guardrails

- Do not run or modify `scenario_runner` from this skill.
- Do not author `authoring-plan.yaml` from scratch in this skill when `agent-plan-authoring` is the correct branch.
- Do not expand coverage scope or invent new cases unless the user explicitly asks for downstream rewriting.
- Do not skip `--validate-agent-plan` after manually editing structured input.
- Do not treat generated draft markdown as executable or reviewed scenarios.
- Do not auto-promote after a generation-only request or overwrite existing scenario files.
- When the user explicitly asks for scenario files for the whole rendered set, continue through review and use `--promote-all-drafts`.

# References

- `references/input-modes.md`
- `references/agent-plan-authoring.md`
- `references/decomposition-workflow.md`
- `references/downstream-modes.md`
