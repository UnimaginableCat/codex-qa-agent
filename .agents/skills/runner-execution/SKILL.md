---
name: runner-execution
description: Execute runnable QA scenario markdown files through the local scenario_runner CLI instead of ad hoc API/DB replay. Use when the user asks to run, validate, execute, resume, inspect, debug, or report a scenario; when a scenario file under scenarios/ exists; when guided/manual mode, pause-state inspection, operator actions, or resume from pause-state.json are needed; or when artifacts such as summary.json/report.md/journal.jsonl must be interpreted.
---

# Purpose

Use this skill as the default path for runnable scenario-based QA in this workspace.

Apply the shared workspace instructions from `qa-entrypoint` first. This skill adds runner-specific execution and pause/resume rules.

Prefer `scenario_runner` over manual API/DB replay when a valid scenario file or scenario directory exists. The runner owns execution semantics; direct API/DB investigation is only a fallback for runner startup failures, contradictory artifacts, or explicit debugging requests.

# Architecture Boundaries

- Engine: lifecycle, step execution, pause/resume, operator decisions, outcomes, and termination semantics.
- Projections: summary, report, guided diagnostics, and operator-facing read models.
- Persistence: run state, pause state, journal, summary, report, and step artifacts.
- CLI: thin adapter over service contracts. Do not duplicate orchestration, pause/resume, or operator action logic in the agent.
- Runner code, parser semantics, and generated scenario markdown are not part of scenario execution evidence. Do not modify `tools/scenario_runner/*` or `scenarios/generated/*` during a scenario run to make a paused or failing scenario continue. Treat missing runner support or invalid generated markdown as a `BLOCKED`/tooling defect and route back to tool development or generation repair.

# Core Commands

Use the workspace-root venv interpreter for runner execution. Do not use target project venvs under `code/<project>` for workspace runner CLI. Verify that the workspace venv exists and satisfies Python 3.14+ before running the CLI. Probe readiness with the public runner CLI needed for the request, for example `<candidate> -m tools.scenario_runner.batch_cli --help` for suites or `<candidate> -m tools.scenario_runner.cli --help` for one scenario. Store the first passing candidate and reuse that exact `<venv-python>` for the run; do not hard-code a different root candidate after probing. If the root venv executable resolves to an external base interpreter through a symlink, do not treat that alone as failure; rely on whether the runner CLI guard accepts the active workspace venv prefix. If a probe has no stdout and no `usage:`/status evidence, treat readiness as unknown and rerun the public CLI probe.

- Auto batch run: `<venv-python> -m tools.scenario_runner.batch_cli --scenario-dir <scenario-dir> --mode auto`
- Guided batch run: `<venv-python> -m tools.scenario_runner.batch_cli --scenario-dir <scenario-dir>`
- Auto run: `<venv-python> -m tools.scenario_runner.cli --scenario <scenario.md>`
- Guided run: `<venv-python> -m tools.scenario_runner.cli --scenario <scenario.md> --mode guided`
- Inspect pause: `<venv-python> -m tools.scenario_runner.cli --inspect-pause <pause-state.json>`
- Resume: `<venv-python> -m tools.scenario_runner.cli --resume <pause-state.json> --action <action_id>`

Do not silently fall back to project venvs, system `python`, `python3`, `py`, or `uv run`. If the workspace-root venv is missing, too old, or lacks dependencies, report the run as environment/tooling `BLOCKED` unless the user explicitly authorizes a non-workspace fallback.

# Execution Policy

Use the runner as the first source of execution truth for runnable scenarios.

- Scenario directory input: use `tools.scenario_runner.batch_cli` for a directory/suite of markdown scenarios instead of building ad hoc shell or inline Python loops.
- Generated scenario directory input such as `scenarios/generated/<source>-<run_id>/`: treat it as a normal scenario suite and execute it with `tools.scenario_runner.batch_cli`.
- Auto mode: use for explicitly non-interactive or compatibility-focused runs.
- Guided mode: use as the default for scenario runs when the user did not request auto/non-interactive mode.
- Manual/resume mode: use only when inspecting an existing pause-state or continuing with an explicit operator action.

Guided/manual mode does not mean asking the operator before every scenario step. Ask the operator only when runner output contains a real pause/decision artifact, such as `operator_state.resumable=true`, `pause_state_path`, and an active decision point with available actions.

If the run finishes terminally without a pause-state or active decision point, report the terminal result. Do not simulate an interactive session or ask for an action that the runner did not expose.

For guided batch execution, stop at the first real paused scenario returned by `batch_cli`. Report the batch summary, the paused scenario `summary`, `operator_state`, and the remaining scenario count. Do not continue the rest of the suite until the operator resolves that pause.

If an API step returns `404` with an HTML/text body while `API_BASE_URL` and the actor profile are resolvable, treat this as likely wrong authored route path after the base URL. Do not guess prefixes such as `/api` or `/api/v1`, do not edit promoted markdown, and do not replay raw `requests` outside the runner to find a working path. Report the paused run and route defect, then route the fix back to the source generation bundle so `operation-inventory.yaml` records `runtime_path_evidence` for the final path after `API_BASE_URL`.

If an action-like API step such as export/download/search/calculate returns `405 Method Not Allowed`, treat it as a likely authored method-evidence defect. Report the runner artifact and route the fix back to the source generation bundle; do not edit promoted markdown or retry with another method outside the runner.

If a permission setup step succeeds but the later actor action is denied, treat this as a likely actor/principal identity binding defect when the setup subject came from a generic list capture such as the first user/member/principal id in a management response. Report that the generated source must prove the granted identity belongs to the actor profile executing the gated step.

# Default Guided Request

When the user asks to run a scenario without specifying mode, treat this as the preferred guided workflow.

Also apply this mandatory environment rule: use the workspace-root venv for the runner; if that venv cannot run the CLI, stop as environment/tooling `BLOCKED` instead of switching interpreters.

```text
Выполни scenario через runner-execution в guided mode: scenarios/<path>.md.
Используй scenario_runner CLI строго через venv в корне workspace, проверь Python 3.14+ interpreter в этом venv, запусти --mode guided.
Если run остановится на pause/decision point, покажи operator_state, available_actions и pause_state_path, но не выбирай action без моего подтверждения.
После моего выбора продолжи через --resume <pause-state.json> --action <action_id>.
В финале дай status, continuation/termination, summary/report paths и ключевые blockers/failures.
```

For scenario directories:

```text
Выполни suite через runner-execution в guided mode: scenarios/<dir>/.
Используй tools.scenario_runner.batch_cli строго через venv в корне workspace.
Если batch дойдет до реального pause-state, остановись на первом paused scenario, покажи batch_summary, summary, operator_state, remaining_scenarios и pause_state_path.
Не собирай временные inline Python или shell loops для массового прогона, если directory suite можно выполнить через batch_cli.
```

# Default Flow

1. Read `AGENTS.md` and the target scenario.
2. Identify the target project under `code/` and the declared env file.
3. Resolve the workspace-root venv interpreter and verify Python 3.14+.
4. If the input is one scenario file, execute `tools.scenario_runner.cli`. If the input is a scenario directory/suite, execute `tools.scenario_runner.batch_cli`.
5. Use guided mode unless the user explicitly requested auto/non-interactive mode.
6. Parse runner JSON output.
7. For single-scenario runs, read runner artifacts after execution: at minimum `.codex-qa/runs/<run-id>/summary.json` and `artifacts/agent/scenario-runs/<run-id>/report.md` when they exist.
8. For batch runs, read `artifacts/agent/scenario-batches/<batch-id>/summary.json` and `report.md`, and when needed drill into the per-run artifacts for the specific scenario run ids returned by the batch payload.
9. If guided output has a real pause/decision point, report `operator_state`, `available_actions`, and `pause_state_path` instead of inventing a choice.
10. If the run is terminal without a pause-state, report the terminal status and continuation/termination semantics without asking for an operator action.
11. Resume only when the user selected or explicitly authorized an action.
12. Use code-analysis/debugging only after the runner result when artifacts show `FAIL`, `BLOCKED`, `ERROR`, contradictions, incomplete evidence, or the user explicitly asks for investigation.
    For terminal `FAIL`/`ERROR`, do targeted implementation analysis before the final report unless the user explicitly asked for status-only output.
    If only a small subset failed, inspect each failed run's `report.md`/`summary.json`/`journal.jsonl` and then the narrow implementation path tied to the failing endpoint/assertion.
    Classify each failure as product behavior, scenario expectation defect, environment/setup issue, or unresolved evidence; do not stop at "likely" without code or artifact evidence.
13. Return final status, continuation/termination state, key blockers/failures, artifact paths, and interpreter used.

# Guided/Manual Handling

In guided/manual mode, treat `operator_state` as the operator-facing read model. Check:

- `run_id`
- `run_mode`
- `continuation_state`
- `final_status`
- `resumable`
- `pause_state_path`
- `active_decision_point`
- `available_actions`
- `recommended_action_id`
- `required_inputs`
- `resume_instructions`
- `run_termination`

If resumable, present `available_actions[].action_id` and wait for the selected action unless the user already gave one. Use `--resume ... --action <action_id>`; do not edit pause-state JSON manually.

If not resumable, do not ask the user to choose an action. Explain that the run reached a terminal state and provide the status, termination reason, and artifact paths.

For guided batch output, first inspect `batch_summary`:

- `final_status`
- `continuation_state`
- `scenario_count_total`
- `scenario_count_executed`
- `scenario_count_remaining`
- `status_counts`
- `items`
- `paused_run_id`
- `paused_pause_state_path`

If the batch payload also includes `summary` and `operator_state`, treat that as the active paused scenario that needs operator input.

# Status Interpretation

Keep these separate:

- Legacy reporting status: `PASS`, `FAIL`, `BLOCKED`, `ERROR`.
- Continuation/lifecycle: active, paused, resumed, terminal.
- Termination semantics: completed, failed, blocked, errored, skipped, aborted, partially completed.
- Operator resolution: selected action and resume strategy.

Use the shared status model from `qa-entrypoint`. For runner outcomes, continue to keep operator state and termination semantics separate from report status.

# When More Detail Is Needed

Read these references only when needed:

- `references/commands-and-artifacts.md`: exact CLI payloads, artifacts to inspect, and output fields.
- `references/runtime-environment.md`: Python selection, dependency/preflight, and network reachability rules.
- `references/variables-and-status.md`: variable DSL, legacy status priority, and guided termination interpretation.

# Guardrails

- Never write source code into `artifacts/`.
- Do not bypass the runner unless it cannot start or the user explicitly asks for manual debugging.
- When manual API/DB debugging is explicitly needed, use `api-workflow` / `tools/api/run_request.py` and `db-verification` / `tools/db/query_check.py`; do not hand-roll env parsing, `requests`, or direct `psycopg` snippets that bypass actor-scoped env loaders and structured runtime signals.
- Do not change runner source code, parser field support, pause-state JSON, or generated scenario files while handling a runner pause. If the run exposes unsupported scenario semantics, report the blocker and stop for an explicit tool/generation fix request.
