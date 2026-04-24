---
name: test-plan-generation
description: Generate a typed NormalizedTestPlan in the local codex-qa-agent workspace. Prefer agent-authored structured plan input when the agent can decompose the request; use prose input only as fallback/bootstrap. Use when the desired output is PlannedTestCase items plus diagnostics/artifacts rather than scenario_runner execution.
---

# Purpose

Use this skill as the default path for test-plan generation in this workspace.

Prefer the structured `agent_plan` path over prose normalization when the agent can decompose a
feature, controller, or API request into explicit planned cases. Prose mode exists only as
fallback/bootstrap when no meaningful decomposition is available yet.

The canonical output remains `NormalizedTestPlan`. Optional downstream stages are:

- `render`
- `review`
- `promote`
- `validate`

Lifecycle:

```text
request -> agent plan -> normalized plan -> drafts -> review -> promoted scenarios -> validation
```

# Operating Modes

- `generate`: create or update `agent-plan.json`, validate it, and produce `normalized-plan.json`.
- `render`: render markdown draft scenarios from the generated plan.
- `promote`: review rendered drafts and promote selected or all drafts into `scenarios/generated`.
- `validate`: validate promoted scenario markdown after editing or readiness checks.

Use the minimum mode that satisfies the request. Stop at `NormalizedTestPlan` unless the user asked
for later phases.

# Core Commands

- Scaffold structured plan:
  `<venv-python> -m tools.generation.cli --init-agent-plan --output artifacts/agent/generation --source-id <id> --project code/<project> --name "<title>" --goal "<goal>"`
- Validate structured plan:
  `<venv-python> -m tools.generation.cli --validate-agent-plan --agent-plan-file <bundle>/agent-plan.json --output-format text`
- Generate from structured plan:
  `<venv-python> -m tools.generation.cli --agent-plan-file <bundle>/agent-plan.json --workspace-root .`
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

- Use `agent_plan` unless the request is too vague or the user explicitly wants prose bootstrap.
- Decompose first for controller, feature, lifecycle, workflow, validation, or API-surface requests.
- Validate structured input before generation when the agent authored or edited JSON.
- Stop at `NormalizedTestPlan` unless the user asked for downstream phases.
- When the user asks for scenario markdown previews, stop after `render`.
- When the user asks for real scenario files, continue through `review` and then `promote`.
- When the user asks to convert the whole rendered set, prefer `--promote-all-drafts` over shell loops.
- When the user asks only for validation/readiness, do not re-generate unless required artifacts are missing.

# Authoring Guidance

- Keep the first plan compact. A good default is roughly `8-10` strong cases unless the user explicitly asked for exhaustive coverage.
- Prefer operation-first coverage over branch-by-branch code inventory.
- When the request is about a full workflow or full controller functionality, prefer at least one true end-to-end case with `workflow_steps[]`.
- For successful state-changing workflow cases, include persisted-state verification with `db_verification` or a `db` workflow step.
- For `kind=api` and `kind=db`, treat `expected_outcomes[]` as runner-compatible expectation DSL, not free-form prose.
- Put high-level behavior into `observable_outcomes[]` and use `expected_outcomes[]` only for executable assertions.

# Rendering Rule

Draft rendering is authored-route-first:

- single-endpoint API cases should define `route`
- workflow cases should define complete `workflow_steps[]`
- rendering should not invent missing route, auth, payload, or DB details

# Guardrails

- Do not run or modify `scenario_runner` from this skill.
- Do not force broad requests through prose scanning when the agent can author a structured plan.
- Do not skip `--validate-agent-plan` after manually editing structured input.
- Do not treat generated draft markdown as executable or reviewed scenarios.
- Do not auto-promote after a generation-only request or overwrite existing scenario files.
- When the user explicitly asks for scenario files for the whole rendered set, continue through review and use `--promote-all-drafts`.

# References

- `references/input-modes.md`
- `references/agent-plan-authoring.md`
- `references/decomposition-workflow.md`
- `references/downstream-modes.md`
