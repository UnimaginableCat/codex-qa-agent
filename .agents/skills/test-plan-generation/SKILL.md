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

- `compile`: compile bundle-local `authoring-plan.yaml` into managed `agent-plan.json` inside the same generation bundle.
- `generate`: accept compiled input, validate it, and produce `normalized-plan.json`.
- `render`: render markdown draft scenarios from the generated plan.
- `review`: inspect rendered drafts and classify promotion readiness.
- `promote`: promote selected or all reviewed drafts into `scenarios/generated`.
- `validate`: validate promoted scenario markdown after editing or readiness checks.

Use the minimum mode that satisfies the request. Stop at `NormalizedTestPlan` unless the user asked
for later phases.

# Core Commands

Apply the `AGENTS.md` workspace interpreter rule before the first command. Resolve `<venv-python>` with the public generation CLI probe (`-m tools.generation.cli --help`) and reuse that exact interpreter for all downstream commands.

- Validate compiled plan:
  `<venv-python> -m tools.generation.cli --validate-agent-plan --agent-plan-file <bundle>/agent-plan.json --output-format text`
- Validate authoring DSL:
  `<venv-python> -m tools.generation.cli --validate-authoring-plan --authoring-plan-file <bundle>/authoring-plan.yaml --output-format text`
- Validate staged authoring bundle:
  `<venv-python> -m tools.generation.cli --validate-authoring-bundle --path <bundle> --output-format text`
- Scaffold authoring DSL bundle:
  `<venv-python> -m tools.generation.cli --init-authoring-plan --output artifacts/agent/generation --source-id <id> --project code/<project> --name "<title>" --goal "<goal>"`
- Compile authoring DSL:
  `<venv-python> -m tools.generation.cli --compile-authoring-plan --authoring-plan-file <bundle>/authoring-plan.yaml --output artifacts/agent/generation --output-format text`
- Generate from structured plan:
  `<venv-python> -m tools.generation.cli --agent-plan-file <bundle>/agent-plan.json --workspace-root . --output-format text`
- Generate from authoring DSL:
  `<venv-python> -m tools.generation.cli --authoring-plan-file <bundle>/authoring-plan.yaml --workspace-root . --output-format text`
- Prose fallback:
  `<venv-python> -m tools.generation.cli --source-id <id> --project code/<project> --prose "<text>" --workspace-root .`
- Render drafts:
  `<venv-python> -m tools.generation.cli --agent-plan-file <bundle>/agent-plan.json --workspace-root . --render-drafts --output-format text`
- Review drafts:
  `<venv-python> -m tools.generation.cli --review-drafts --run-id <generation-run-id> --workspace-root . --output-format json`
- Promote one:
  `<venv-python> -m tools.generation.cli --promote-draft --run-id <generation-run-id> --draft-id <draft-id> --workspace-root . --target-dir scenarios/generated --output-format json`
- Promote all:
  `<venv-python> -m tools.generation.cli --promote-all-drafts --run-id <generation-run-id> --workspace-root . --target-dir scenarios/generated --output-format json`
- Re-promote after rerender:
  `<venv-python> -m tools.generation.cli --promote-all-drafts --run-id <generation-run-id> --workspace-root . --target-dir scenarios/generated --purge-target-dir --output-format json`
- Validate promoted directory:
  `<venv-python> -m tools.generation.cli --validate-scenario-dir --path scenarios/generated/<source>-<run_id> --mode compile --output-format text`
- Validate scenario:
  `<venv-python> -m tools.generation.cli --validate-scenario --path scenarios/generated/<file>.md --output-format text`

Every command used as a gate must produce explicit status evidence before the workflow continues. Empty stdout, a
truncated payload, or output that lacks `Status: ...`/JSON `status` is not a successful gate. Rerun with
`--output-format json`, inspect the persisted result artifact, or report tooling `ERROR`/`BLOCKED` instead of
continuing.

For `--review-drafts`, use the returned `review_result_path` when stdout is long or truncated. Do not read
generation `summary.json` as if it contained the latest review set.

# Default Decisions

- Use compiled input unless the request is too vague or the user explicitly wants prose bootstrap.
- Expect `artifacts/agent/generation/<run_id>/authoring-plan.yaml` or compiled `agent-plan.json` from the same bundle as the normal input.
- Route decomposition-first requests back to `agent-plan-authoring`.
- Validate authoring or compiled input before generation when the agent edited source artifacts.
- Stop at `NormalizedTestPlan` unless the user asked for downstream phases.
- When the user asks for scenario markdown previews, stop after `render`.
- When the user asks for real scenario files, continue through `review` and then `promote`.
- When the user asks to run the generated scenarios after promotion, hand off to `qa-generation-pipeline` or `runner-execution`; this skill does not execute scenarios.
- When the user asks to convert the whole rendered set, prefer `--promote-all-drafts` over shell loops.
- When the user asks only for validation/readiness, do not re-generate unless required artifacts are missing.

# Downstream Guidance

Treat this skill as a consumer of authored input. It compiles, renders, reviews, promotes, and validates; it does not design new coverage unless explicitly asked.

Core rules:

- Preserve first-class `scenario_variables[]`, workflow steps, captures, DB verification, actor profiles, and author intent from source artifacts.
- If compile/render/review/preflight reveals a source defect, repair the bundle under `artifacts/agent/generation/<run_id>/` and rerun gates.
- If operation inventory lacks `success_status_evidence` for a mutating/action-like route, repair the source bundle before compile/render; method evidence is not status evidence.
- Do not patch `scenarios/generated/` as the primary fix; promoted scenarios must be reproducible from generation artifacts.
- Treat review edit targets, unsupported checks, deferred executable cases, and unresolved data setup as blockers to clean promotion.
- Treat preflight blockers as readiness issues, not permission to shrink coverage.

Read `references/repair-policy.md` when diagnosing review, promotion, validation, preflight, or generated scenario failures.

## Quality Gates

- `validate-authoring-bundle` is the managed staged-bundle gate before compile/generate.
- `validate-agent-plan` is necessary but not sufficient for promoted runnable scenarios.
- Review is clean only when status is PASS, drafts are valid, deferred count is zero, and `total_edit_targets = 0`.
- Review/promotion do not override missing or contradictory source status evidence; fix the authoring bundle instead of accepting a plausible HTTP expectation.
- Promotion is clean only when all requested drafts are promoted with zero errors and zero blocked items.
- Before re-promoting an existing run-scoped directory, use `--purge-target-dir` only for intentional regeneration.

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
- Do not treat promote or validate as execution; actual generated scenario runs belong to `qa-generation-pipeline` coordinating `runner-execution`.
- Do not author `authoring-plan.yaml` from scratch in this skill when `agent-plan-authoring` is the correct branch.
- Do not scaffold a new authoring bundle here unless the user explicitly bypassed routing and asked to start with downstream CLI primitives.
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
- `references/repair-policy.md`
