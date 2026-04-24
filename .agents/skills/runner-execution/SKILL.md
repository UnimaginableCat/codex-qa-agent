---
name: runner-execution
description: Execute runnable QA scenario markdown files through the local scenario_runner CLI instead of ad hoc API/DB replay. Use when the user asks to run, validate, execute, resume, inspect, debug, or report a scenario; when a scenario file under scenarios/ exists; when guided/manual mode, pause-state inspection, operator actions, or resume from pause-state.json are needed; or when artifacts such as summary.json/report.md/journal.jsonl must be interpreted.
---

# Purpose

Use this skill as the default path for runnable scenario-based QA in this workspace.

Apply the shared workspace instructions from `qa-entrypoint` first. This skill adds runner-specific execution and pause/resume rules.

Prefer `scenario_runner` over manual API/DB replay when a valid scenario file exists. The runner owns execution semantics; direct API/DB investigation is only a fallback for runner startup failures, contradictory artifacts, or explicit debugging requests.

# Architecture Boundaries

- Engine: lifecycle, step execution, pause/resume, operator decisions, outcomes, and termination semantics.
- Projections: summary, report, guided diagnostics, and operator-facing read models.
- Persistence: run state, pause state, journal, summary, report, and step artifacts.
- CLI: thin adapter over service contracts. Do not duplicate orchestration, pause/resume, or operator action logic in the agent.

# Core Commands

Use the project/workspace venv interpreter for runner execution. Verify that the venv exists and satisfies Python 3.14+ before running the CLI.

- Auto run: `<venv-python> -m tools.scenario_runner.cli --scenario <scenario.md>`
- Guided run: `<venv-python> -m tools.scenario_runner.cli --scenario <scenario.md> --mode guided`
- Inspect pause: `<venv-python> -m tools.scenario_runner.cli --inspect-pause <pause-state.json>`
- Resume: `<venv-python> -m tools.scenario_runner.cli --resume <pause-state.json> --action <action_id>`

Do not silently fall back to system `python` or `py`. If the project venv is missing, too old, or lacks dependencies, report the run as environment/tooling `BLOCKED` unless the user explicitly authorizes a non-venv fallback.

# Execution Policy

Use the runner as the first source of execution truth for runnable scenarios.

- Auto mode: use for explicitly non-interactive or compatibility-focused runs.
- Guided mode: use as the default for scenario runs when the user did not request auto/non-interactive mode.
- Manual/resume mode: use only when inspecting an existing pause-state or continuing with an explicit operator action.

Guided/manual mode does not mean asking the operator before every scenario step. Ask the operator only when runner output contains a real pause/decision artifact, such as `operator_state.resumable=true`, `pause_state_path`, and an active decision point with available actions.

If the run finishes terminally without a pause-state or active decision point, report the terminal result. Do not simulate an interactive session or ask for an action that the runner did not expose.

# Default Guided Request

When the user asks to run a scenario without specifying mode, treat this as the preferred guided workflow:

Also apply this mandatory environment rule: use the project/workspace venv for the runner; if the venv cannot run the CLI, stop as environment/tooling `BLOCKED` instead of switching interpreters.

```text
Выполни scenario через runner-execution в guided mode: scenarios/<path>.md.
Используй scenario_runner CLI строго через venv проекта, проверь Python 3.14+ interpreter в этом venv, запусти --mode guided.
Если run остановится на pause/decision point, покажи operator_state, available_actions и pause_state_path, но не выбирай action без моего подтверждения.
После моего выбора продолжи через --resume <pause-state.json> --action <action_id>.
В финале дай status, continuation/termination, summary/report paths и ключевые blockers/failures.
```

# Default Flow

1. Read `AGENTS.md` and the target scenario.
2. Identify the target project under `code/` and the declared env file.
3. Resolve the project/workspace venv interpreter and verify Python 3.14+.
4. Execute the runner CLI first; use guided mode unless the user explicitly requested auto/non-interactive mode.
5. Parse runner JSON output.
6. Read runner artifacts after execution: at minimum `.codex-qa/runs/<run-id>/summary.json` and `artifacts/agent/<scenario-slug>-<run-id>/report.md` when they exist.
7. If guided output has a real pause/decision point, report `operator_state`, `available_actions`, and `pause_state_path` instead of inventing a choice.
8. If the run is terminal without a pause-state, report the terminal status and continuation/termination semantics without asking for an operator action.
9. Resume only when the user selected or explicitly authorized an action.
10. Use code-analysis/debugging only after the runner result when artifacts show `FAIL`, `BLOCKED`, `ERROR`, contradictions, incomplete evidence, or the user explicitly asks for investigation.
11. Return final status, continuation/termination state, key blockers/failures, artifact paths, and interpreter used.

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
