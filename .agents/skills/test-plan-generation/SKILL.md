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
- Treat `generate` as authoring an execution-oriented plan, not a coverage-only outline that will be fixed by hand later.
- For broad requests such as "cover the whole controller" or "full functionality", keep the requested scope but author incrementally inside `generate`: start with `1-2` representative seed cases, make them structurally executable, validate the plan, and only then expand the remaining cases.
- When the request is about a full workflow or full controller functionality, prefer at least one true end-to-end case with `workflow_steps[]`.
- For successful state-changing workflow cases, include persisted-state verification with `db_verification` or a `db` workflow step.
- For `kind=api` and `kind=db`, treat `expected_outcomes[]` as runner-compatible expectation DSL, not free-form prose.
- When an expected value depends on normalization or transformation, author a derived/template/captured variable for the post-transform value and assert against that. Do not reuse raw input placeholders in normalized expectations.
- Split independent negative or validation variants into separate executable cases or explicit `workflow_steps[]`. Do not compress multiple invalid requests into one prose-only case.
- Put high-level behavior into `observable_outcomes[]` and use `expected_outcomes[]` only for executable assertions.
- Do not author standalone cases that depend on seeded, pre-existing, or operator-supplied entity ids unless that dependency is already modeled as machine-readable setup. If a case needs an existing entity, prefer `workflow_steps[]` that create/setup it first.
- Do not treat unresolved variable declarations such as `run_suffix`, `email_suffix`, generated UUIDs, or other machine-readable scenario variables as acceptable runnable-case leftovers. Either author the variable flow concretely or keep the case explicitly unresolved.
- Do not accept weak proof cases whose executable assertions stop at transport-level checks such as `HTTP 200` or `response JSON is an array` when the objective claims business filtering, matching, mutation, or validation behavior. Author at least one deterministic assertion that proves the stated behavior.
- For negative mutating cases that claim "does not create", "does not update", or "status remains unchanged", include deterministic persisted-state verification whenever the claimed non-effect is observable through DB checks.
- Treat cases with unresolved data setup, assertion detail, auth strategy, environment selection, or executable detail as non-runnable authoring defects to fix in `agent-plan.json`, not as acceptable near-runnable coverage.

## Quality Gates

- `validate-agent-plan` is the minimum gate, not the only gate.
- If later phases are requested, treat render/review/compile warnings as authoring defects to fix back in `agent-plan.json`, not as acceptable follow-up manual cleanup.
- Do not continue expanding a full-controller plan after the first seed cases if those cases still show DSL, workflow-shape, capture, or DB-verification problems.
- Do not treat drafts with unresolved `data_setup`, `assertion_detail`, `environment`, `auth_strategy`, or `executable_detail` gaps as close to runnable or promotable. Return to `agent-plan.json` and fix the source plan instead.
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
- if render/review shows missing assertions, captures, or DB checks for a case intended for execution, return to `agent-plan.json` and fix the source plan before promotion
- drafts with execution-blocking typed gaps should remain deferred rather than being treated as acceptable preview candidates for promotion

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
