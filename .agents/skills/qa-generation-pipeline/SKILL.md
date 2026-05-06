---
name: qa-generation-pipeline
description: Orchestrate the full local QA generation pipeline from authoring through scenario execution. Use when the user asks for an end-to-end flow such as generate plans, compile, render, review, promote, validate, and run generated scenarios; "full generation pipeline"; "authoring to runner"; "generate scenarios and execute them"; or when a generation bundle under artifacts/agent/generation must be carried through to scenario_runner execution.
---

# Purpose

Use this skill as the thin orchestration layer for the complete QA generation path.

This skill coordinates existing specialized skills. It does not replace them:

- `agent-plan-authoring` owns staged coverage authoring.
- `test-plan-generation` owns compile, generate, render, review, promote, and scenario markdown validation.
- `runner-execution` owns actual execution of promoted scenarios through `scenario_runner`.
- `reporting` owns final synthesis when an execution/investigation report is requested.

# Canonical Flow

```text
scope or existing bundle
-> staged authoring bundle
-> validate authoring bundle
-> compile agent-plan.json
-> validate compiled plan
-> generate normalized-plan.json
-> render draft scenarios
-> review drafts
-> promote scenario markdown
-> validate promoted scenario directory
-> execute promoted scenarios through scenario_runner
-> final report
```

# Routing

Start here when the request crosses generation and execution boundaries.

Use the minimum path needed:

- Existing promoted scenario file or directory: skip generation and use `runner-execution`.
- Existing generation bundle with valid `authoring-plan.yaml`: start at validation or compile.
- Existing `agent-plan.json`: start at validate compiled plan or generate/render.
- Broad coverage request with no bundle: start with `agent-plan-authoring`.
- Request only for markdown previews: stop after render/review; do not promote or run unless requested.
- Request for scenario files: continue through review, promote, and promoted scenario validation.
- Request to run generated scenarios: continue through `runner-execution`.

Always identify the target project under `code/` before authoring or execution. If the project is ambiguous, make the smallest reasonable assumption and state it.

# Stage Gates

Do not continue past a failed gate unless the user explicitly asks for diagnostic-only continuation.

Required gates:

1. Authoring bundle gate:
   `<venv-python> -m tools.generation.cli --validate-authoring-bundle --path artifacts/agent/generation/<run_id> --output-format text`
2. Compile gate:
   `<venv-python> -m tools.generation.cli --compile-authoring-plan --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml --output artifacts/agent/generation --output-format text`
3. Compiled plan gate:
   `<venv-python> -m tools.generation.cli --validate-agent-plan --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json --output-format text`
4. Render gate:
   `<venv-python> -m tools.generation.cli --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json --workspace-root . --render-drafts --output-format text`
5. Review gate:
   `<venv-python> -m tools.generation.cli --review-drafts --run-id <generation-run-id> --workspace-root . --output-format json`
6. Promotion gate:
   `<venv-python> -m tools.generation.cli --promote-all-drafts --run-id <generation-run-id> --workspace-root . --target-dir scenarios/generated --output-format json`
7. Promoted scenario validation gate:
   `<venv-python> -m tools.generation.cli --validate-scenario-dir --path scenarios/generated/<source>-<run_id> --mode compile --output-format text`
8. Execution gate:
   `<venv-python> -m tools.scenario_runner.batch_cli --scenario-dir scenarios/generated/<source>-<run_id>`

For every gate, inspect an explicit status from stdout or a persisted artifact. If a command returns no stdout, do not infer `PASS`; rerun with JSON/text output, check the exit code, or read the relevant result artifact before continuing.

For review and promotion gates, prefer JSON and verify numeric counts before continuing:

- review: require `status=PASS`, `draft_count > 0`, `invalid_draft_count = 0`, `deferred_item_count = 0`, and `total_edit_targets = 0`
- review: report `drafts_with_edit_targets`, `total_edit_targets`, `drafts_with_high_priority_edit_targets`, and `high_priority_edit_target_count` explicitly; do not summarize review as clean solely because `status=PASS`
- promotion: require `status=PASS`, `promoted_count = requested_count`, `error_count = 0`, and `blocked_count = 0`
- promotion: if review finds edit targets or a non-promotable advisory, repair source authoring/drafts before promotion; use `--allow-known-gaps --known-gaps-reviewed` only when the operator explicitly accepts the concrete review findings. A request that includes `promote` in the desired stage list is not consent to promote known gaps.

Use guided runner mode by default. Use auto mode only when the user explicitly asks for non-interactive execution.

# Artifact Handling

Treat `artifacts/agent/generation/<run_id>/` as the generation source of truth.

Read generation artifacts when present:

- `summary.json`
- `manifest.json`
- `diagnostics.json`
- `normalized-plan.json`
- `scenario-render-result.json`
- `scenario-parse-results.json`
- `unsupported-checks.json`
- `deferred-items.json`
- `promotion-result.json`

Treat promoted scenarios under `scenarios/generated/<source>-<run_id>/` as runner inputs, not as generation artifacts.

Do not edit generated reports, summaries, manifests, raw runner artifacts, or promotion outputs unless the user explicitly asks for artifact repair. If a draft or promoted scenario has an execution-blocking defect, repair the source authoring bundle and rerun downstream stages; do not hot-patch `scenarios/generated/` as the primary fix.

# Failure Policy

Use the shared status model:

- `PASS`: stage executed and matched expectations.
- `FAIL`: stage executed, but expectations were not met.
- `BLOCKED`: missing config, env, auth, access, dependency, venv, or setup.
- `ERROR`: CLI/runtime/parser/unexpected technical failure.

Final status priority:

1. `ERROR`
2. `BLOCKED`
3. `FAIL`
4. `PASS`

Stop conditions:

- Authoring validation fails: return to `agent-plan-authoring` and repair the staged bundle.
- Authoring validation emits `authoring_workflow_setup_state_mismatch`: stop and repair authoring unless a same-state lifecycle contract in `operation-inventory.yaml` explicitly proves that the mismatch is the intended behavior.
- Render has deferred execution-critical cases: repair source authoring before promotion.
- Review says drafts are not promotable: repair source authoring or selected draft source.
- Review reports stateful preconditions such as "before this case runs": repair authoring so the setup is self-contained, uses a dedicated fixture, or remains deferred.
- Review or compile reports unsupported step fields: repair source authoring or rendering support; do not patch runner semantics during scenario execution. Step-level `Actor:` is supported and should be preserved for multi-actor workflows.
- Promotion detects placeholder or mismatched `context.json` metadata: rerun/fix the managed generation step; do not edit `context.json` or `manifest.json` by hand.
- Promotion writes zero scenarios: stop and report `FAIL` or `BLOCKED` depending on diagnostics.
- Promoted scenario validation fails: repair source authoring or promoted scenario only if explicitly asked.
- Promoted scenario compile validation reports `compile_valid_but_incomplete` only because env-backed inputs are unresolved: run `--validate-scenario-dir --mode preflight` or explicitly state that runner preflight is the next readiness check before batch execution.
- Runner pauses in guided mode: show `operator_state`, available actions, and `pause_state_path`; wait for the operator choice.
- Runner API step returns `404` HTML/text while `API_BASE_URL` and actor auth resolved: stop the execution path and repair the source authoring bundle. The likely defect is the authored path after `API_BASE_URL`; require `operation-inventory.yaml` route `runtime_path_evidence` proving the final external path before rerendering and re-promoting.
- Runner terminal result: report terminal status without simulating manual decisions.

# Environment Rules

Use the workspace-root venv interpreter for CLI stages. For runner execution, follow `runner-execution` strictly: the workspace venv must exist, satisfy Python 3.14+, and have required dependencies. Do not use target project venvs under `code/<project>` for workspace tooling, and do not silently fall back to system `python`, `python3`, `py`, or `uv run` for scenario execution.

For generation-only stages, if the workspace-root venv is missing or cannot run the generation CLI, report tooling readiness as `BLOCKED` instead of inventing output.

Never print secrets. Preserve env-backed variables as references such as `env:INTERNAL_API_TOKEN`; do not reveal resolved token values.

# Final Response

Include:

- target project
- source request or generation bundle
- promoted scenario directory when created
- runner mode when execution happened
- final status
- stage outcomes
- blockers/failures
- assumptions
- artifact paths for generation and runner outputs

When execution was not requested, explicitly state where the pipeline stopped and which next command or skill would continue it.

# References

Read `references/pipeline-commands.md` when exact command sequencing or artifact mapping is needed.
