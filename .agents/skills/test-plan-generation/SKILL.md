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

Resolve `<venv-python>` before the first command. Use a workspace-root venv interpreter such as `.venv314/Scripts/python.exe`, `.venv/Scripts/python.exe`, `.venv314/bin/python`, or `.venv/bin/python`; do not use target project venvs under `code/<project>`, `python`, `python3`, `py`, or `uv run` as probes before checking the workspace venv. A workspace venv may resolve to an external base interpreter path when it is symlinked by `uv`; rely on whether the workspace CLI guard accepts the active venv prefix, not on resolved executable path alone. If no workspace-root venv can run the generation CLI, stop as tooling `BLOCKED`; use any non-workspace interpreter only after explicit user authorization.

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
  `<venv-python> -m tools.generation.cli --agent-plan-file <bundle>/agent-plan.json --workspace-root .`
- Generate from authoring DSL:
  `<venv-python> -m tools.generation.cli --authoring-plan-file <bundle>/authoring-plan.yaml --workspace-root .`
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
- Re-promote after rerender:
  `<venv-python> -m tools.generation.cli --promote-all-drafts --run-id <generation-run-id> --workspace-root . --target-dir scenarios/generated --purge-target-dir`
- Validate promoted directory:
  `<venv-python> -m tools.generation.cli --validate-scenario-dir --path scenarios/generated/<source>-<run_id> --mode compile --output-format text`
- Validate scenario:
  `<venv-python> -m tools.generation.cli --validate-scenario --path scenarios/generated/<file>.md --output-format text`

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

- Treat this skill as a consumer of authored input, not as a coverage-design skill.
- Preserve author intent while compiling and generating; do not add or expand cases unless the user explicitly asks for that rewrite.
- Treat `expected_outcomes[]`, `capture`, `workflow_steps[]`, and `db_verification` as executable downstream contracts.
- Treat first-class `scenario_variables[]` as the canonical variable channel from authoring through rendered scenarios.
- Keep `metadata.scenario_variables` only as backward-compatibility input when repairing older bundles; do not author new plans that way.
- Expect standalone pure `db-check` cases to compile, but they may remain deferred during draft rendering if they are not expressed as workflow DB steps or attached persisted-state verification.
- Treat rendered `actor = literal:<value>` as an execution profile selector for actor-scoped API/DB env keys, not as decorative notes-only metadata.
- Treat rendered step-level `Actor: <value>` as an intentional per-step override. It lets setup and action steps use different actor-scoped API/DB env profiles inside one workflow.
- If compile, render, or review reveals authoring defects, send the workflow back to `artifacts/agent/generation/<run_id>/authoring-plan.yaml` rather than compensating by inventing new coverage here.
- Treat review/runtime evidence of root-level `price` / `cost_price` assertion failures on price-list JSON responses as an authoring defect unless code evidence proves those fields belong at response root. Repair the source authoring assertion path and rerender; do not patch promoted markdown manually.
- Treat review/runtime evidence of empty search/list visibility results as an authoring defect when the source case declares `metadata.coverage_claims.visibility.requires_non_empty_result: true`. Repair the source with data-creating/discovery setup or an explicit structured fixture/data contract such as `metadata.data_contract.non_empty_paths` plus provenance (`source`, `source_ref`, `evidence`, `setup_operation`, or DB verification) for the exact indexed response path; do not treat a bare `non_empty_paths` entry as readiness proof. For nested indexed assertions such as `categories.0.positions.0.price`, a root length check only proves the root collection; require every indexed collection level, for example both `response categories length >= 1` and `response categories.0.positions length >= 1`, or an equivalent structured fixture/setup contract. Prose-only preconditions/notes are not sufficient to make review clean. An unrelated prior workflow step, auth check, or generic read does not count as data setup unless it proves the asserted collection path.
- Treat runtime HTTP 400 on action-like authored request bodies as a source authoring defect unless implementation evidence proves the product rejected valid input. Return to `agent-plan-authoring` and make request body evidence field-specific; generic evidence like `uses serializer` is not enough to prove that fields such as `template_id`/`count` match the real serializer.
- Treat runtime evidence that a permission grant succeeded but the later actor action is still denied as a likely actor/principal identity binding defect. Repair the source so the granted user/member/principal id is proven to belong to the actor that executes the gated step; do not rely on the first row of a management list matching the actor credentials, and do not satisfy this with weak prose metadata.
- Treat runtime `405 Method Not Allowed` on export/download/search/calculate/action-like endpoints as an authored method-evidence defect. Return to `operation-inventory.yaml`, prove the method from view/controller/service/test source, rerender, review, and re-promote; do not flip GET/POST in promoted markdown. Do not use `source_role: method_handler` to make URLConf/router files such as `urls.py`, `routes.py`, `router.*`, or `routing.*` count as method evidence.
- Treat permission negative/default failures where the actor actually has `can_edit` or `can_create` as fixture-state authoring defects by default. Repair the source case with a structured `metadata.coverage_claims.permissions` contract plus self-contained revoke/reset setup, or a documented stable no-override fixture contract with structured baseline evidence before rerendering. Do not rely on objective/title wording, actor metadata, or a bare `403` response to identify permission intent.
- Treat runtime evidence of `404` with HTML/text body on an API step as a likely authored route defect when `API_BASE_URL` and actor auth are resolvable. Do not fix this by editing promoted markdown or by guessing `/api`, `/api/v1`, or other prefixes. Return to `operation-inventory.yaml` and `authoring-plan.yaml`, prove the final path after `API_BASE_URL` with `runtime_path_evidence`, rerender, review, and re-promote.
- For promoted runnable API scenarios, require the source operation inventory to prove runtime path mounting when route origin is framework/app-local. Prefer `metadata.contracts.routes.runtime_path_evidence_required: true` plus route-level `runtime_path_evidence`. Method evidence from a handler/controller/view/action implementation or test proves method; route mapping sources prove mounting; neither evidence type substitutes for the other.
- Treat `authoring_scope_role_coverage_missing` as a source authoring defect. Repair the source by adding a case that actually runs as the missing role through `metadata.default_actor` or `execute.actor`, by adding a structured `coverage_claims` actor/role claim, or by adding an explicit role waiver. Do not try to satisfy role coverage by editing case titles, objectives, tags, or broad scope prose.
- Treat `authoring_created_entity_capture_overwrites_fixture_variable` and `authoring_created_entity_persistence_uses_fixture_id` as source authoring defects. Repair create cases with a distinct `created_*` capture and a DB verification scoped to that captured id/guid/uuid instead of reusing any predeclared fixture/input identifier.
- Use direct `agent_plan` editing only as a low-level escape hatch for debugging or explicit manual control.
- Do not patch files under `scenarios/generated/` to fix generated scenario defects. Repair the source authoring bundle or compiled plan, rerender, review, and re-promote so the promoted scenario remains reproducible from generation artifacts.

## Quality Gates

- `validate-agent-plan` is the minimum gate, not the only gate.
- `validate-authoring-plan` is a local authoring check, not the final managed-bundle gate.
- For managed staged bundles, `validate-authoring-bundle` is the required pre-compile and pre-generate gate; do not skip straight from edited inventories/authoring-plan into compile or generation.
- If later phases are requested, treat render/review/compile warnings as authoring defects to fix back in the bundle-local `authoring-plan.yaml` or compiled `agent-plan.json`, not as acceptable follow-up manual cleanup.
- Do not treat drafts with unresolved `data_setup`, `assertion_detail`, `environment`, `auth_strategy`, or `executable_detail` gaps as close to runnable or promotable. Return to the source authoring artifact instead.
- Do not use `--allow-known-gaps` merely because high-priority edit targets are zero. A user request that lists `promote` as a pipeline stage is not explicit acceptance of known gaps. Promotion with any review gaps requires explicit operator acceptance of the concrete findings and the CLI confirmation flag `--known-gaps-reviewed`; otherwise stop and repair the source artifacts.
- Treat `total_edit_targets > 0` from review as not clean. Do not promote by default even when every edit target is low priority.
- If promotion reports placeholder or mismatched run metadata in `context.json`, rerun or repair the managed generation command path. Do not manually edit `context.json`, `manifest.json`, or promotion results to change target names.
- Treat preconditions that say another scenario or grant must run first as execution-blocking. Generated scenarios must be independent unless the runner has an explicit dependency contract.
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
