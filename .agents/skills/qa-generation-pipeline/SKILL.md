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

## Bundle Selection

Treat the generation run id as an audit identity. Reusing an existing bundle is appropriate when the user points to that
bundle, when continuing an incomplete pipeline, or when repairing the same active run before the final answer.

For a new broad coverage request, do not silently mutate a historical bundle that already has promoted scenarios or
runner execution artifacts just because its `source_id` is similar. Prefer a new staged bundle, or explicitly state that
you are cloning/extending an existing source bundle and why. In-place edits plus `--purge-target-dir` are reserved for
intentional regeneration of the same active run; before doing that, state the previous promoted count and that the
run-scoped promoted directory will be replaced.

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

For generation gates, inspect an explicit status from stdout or a persisted artifact. If a `tools.generation.cli`
command returns no stdout, do not infer `PASS`; rerun that generation CLI command with JSON/text output, check the exit
code, or read the relevant generation result artifact before continuing. Exit code 0 alone is not gate evidence. A
transcript line such as `(no output)` means the gate status is unknown until you rerun the generation gate with
`--output-format json` or read a persisted result containing `status=PASS`.

The execution gate is different: `tools.scenario_runner.batch_cli` does not support `--output-format`. If a batch run has
no visible stdout yet, keep waiting for the active process or inspect persisted batch artifacts such as
`artifacts/agent/scenario-batches/<batch-id>/summary.json`, `report.md`, and `manifest.json`. Do not retry `batch_cli`
with generation-only flags. Keep a small stage ledger as you work: gate name, observed status, key counts, and artifact
path. Do not batch-chain multiple gates in one shell command when that would make it unclear which gate produced which
status.

For review and promotion gates, prefer JSON and verify numeric counts before continuing:

- review: require `status=PASS`, `draft_count > 0`, `invalid_draft_count = 0`, `deferred_item_count = 0`, and `total_edit_targets = 0`
- review: report `drafts_with_edit_targets`, `total_edit_targets`, `drafts_with_high_priority_edit_targets`, and `high_priority_edit_target_count` explicitly; do not summarize review as clean solely because `status=PASS`
- source status contract: mutating/action-like route expectations must have `success_status_evidence` that explicitly proves the declared status; a clean review is not proof that `201` vs `200` is correct
- source behavior contract: route-specific oracles for defaults, omitted fields, clear/null, duplicate preservation, and remapping must have structured `behavior_evidence` from the same handler/service/test flow. A clean review is not proof that an update-flow expectation is valid for create-flow execution.
- promotion: require `status=PASS`, `promoted_count = requested_count`, `error_count = 0`, and `blocked_count = 0`
- promotion: if review finds edit targets or a non-promotable advisory, repair source authoring/drafts before promotion; use `--allow-known-gaps --known-gaps-reviewed` only when the operator explicitly accepts the concrete review findings. A request that includes `promote` in the desired stage list is not consent to promote known gaps.
- re-promotion: after any source/rerender change, check whether the run-scoped target directory under
  `scenarios/generated/<source>-<run_id>/` already exists before calling promotion. If files exist, expect the default
  promotion command to fail rather than overwrite. Use `--purge-target-dir` only for an intentional run-scoped
  regeneration, and state that it removes the previously promoted files for that generation run before recreating them.

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

Use the shared status model from `AGENTS.md`: `PASS`, `FAIL`, `BLOCKED`, `ERROR`, with priority `ERROR > BLOCKED > FAIL > PASS`.

Core stop rules:

- Failed authoring, compile, render, review, promotion, or scenario validation gates stop the pipeline unless the user explicitly asks for diagnostic-only continuation.
- Repair source generation artifacts instead of editing promoted markdown or generated reports.
- Preflight/readiness blockers are environment/setup blockers, not product failures and not permission to weaken coverage.
- Guided runner pauses require showing the real `operator_state` and waiting for an action.
- Terminal runner `FAIL` or `ERROR` requires reading failed artifacts and targeted implementation/debug analysis unless the user requested status-only output.

Read `references/failure-policy.md` when a gate fails or when deciding whether to repair authoring, classify readiness, or investigate product behavior.

# Environment Rules

Apply the `AGENTS.md` workspace interpreter rule for every stage. Resolve `<venv-python>` once with the public CLI needed by the current stage, reuse that interpreter across the pipeline, and rely on `runner-execution` for runner-specific readiness.

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

- `references/pipeline-commands.md`: exact command sequencing and artifact map.
- `references/failure-policy.md`: detailed stop/repair/classification rules.
