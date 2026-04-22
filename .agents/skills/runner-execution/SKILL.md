---
name: runner-execution
description: Execute runnable QA scenario markdown files through the local scenario_runner CLI instead of ad hoc API/DB replay. Use when the user asks to run, validate, execute, resume, inspect, debug, or report a scenario; when a scenario file under scenarios/ exists; when guided/manual mode, pause-state inspection, operator actions, or resume from pause-state.json are needed; or when artifacts such as summary.json/report.md/journal.jsonl must be interpreted.
---

# Purpose

Use this skill as the default path for runnable scenario-based QA in this workspace.

Prefer `scenario_runner` over manual API/DB replay when a valid scenario file exists. The runner owns execution semantics; direct API/DB investigation is only a fallback for runner startup failures, contradictory artifacts, or explicit debugging requests.

# Architecture Boundaries

- Engine: lifecycle, step execution, pause/resume, operator decisions, outcomes, and termination semantics.
- Projections: summary, report, guided diagnostics, and operator-facing read models.
- Persistence: run state, pause state, journal, summary, report, and step artifacts.
- CLI: thin adapter over service contracts. Do not duplicate orchestration, pause/resume, or operator action logic in the agent.

# Core Commands

Use a Python 3.14+ interpreter. In this workspace, `.venv` may be older than the runner guard; verify version before using it.

- Auto run: `python -m tools.scenario_runner.cli --scenario <scenario.md>`
- Guided run: `python -m tools.scenario_runner.cli --scenario <scenario.md> --mode guided`
- Inspect pause: `python -m tools.scenario_runner.cli --inspect-pause <pause-state.json>`
- Resume: `python -m tools.scenario_runner.cli --resume <pause-state.json> --action <action_id>`

On Windows, `py -m tools.scenario_runner.cli ...` is acceptable when `py` resolves to Python 3.14+ and the local venv does not.

# Default Guided Request

When the user asks to run a scenario without specifying mode, treat this as the preferred guided workflow:

```text
Выполни scenario через runner-execution в guided mode: scenarios/<path>.md.
Используй scenario_runner CLI, проверь Python 3.14+ interpreter, запусти --mode guided.
Если run остановится на pause/decision point, покажи operator_state, available_actions и pause_state_path, но не выбирай action без моего подтверждения.
После моего выбора продолжи через --resume <pause-state.json> --action <action_id>.
В финале дай status, continuation/termination, summary/report paths и ключевые blockers/failures.
```

# Default Flow

1. Read `AGENTS.md` and the target scenario.
2. Identify the target project under `code/` and the declared env file.
3. Resolve a Python 3.14+ runner interpreter.
4. Use auto mode unless the user asks for guided/manual flow or pause/resume handling.
5. Execute the runner CLI and parse its JSON output.
6. Inspect at least `.codex-qa/runs/<run-id>/summary.json` and `artifacts/agent/<scenario-slug>-<run-id>/report.md`.
7. If guided output has `operator_state.resumable=true`, report the active decision and available actions instead of inventing a choice.
8. Resume only when the user selected or explicitly authorized an action.
9. Return final status, continuation/termination state, key blockers/failures, artifact paths, and interpreter used.

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

# Status Interpretation

Keep these separate:

- Legacy reporting status: `PASS`, `FAIL`, `BLOCKED`, `ERROR`.
- Continuation/lifecycle: active, paused, resumed, terminal.
- Termination semantics: completed, failed, blocked, errored, skipped, aborted, partially completed.
- Operator resolution: selected action and resume strategy.

Do not mark a scenario `PASS` if critical steps are `BLOCKED`, `FAIL`, or `ERROR`. Treat auth/config/setup issues as `BLOCKED`, assertion mismatches as `FAIL`, and tool/runtime crashes as `ERROR`.

# When More Detail Is Needed

Read these references only when needed:

- `references/commands-and-artifacts.md`: exact CLI payloads, artifacts to inspect, and output fields.
- `references/runtime-environment.md`: Python selection, dependency/preflight, and network reachability rules.
- `references/variables-and-status.md`: variable DSL, legacy status priority, and guided termination interpretation.

# Guardrails

- Never expose secrets or raw credentials.
- Never write source code into `artifacts/`.
- Never execute destructive or mutating SQL for verification.
- Do not bypass the runner unless it cannot start or the user explicitly asks for manual debugging.
- Do not treat environment/network restrictions as product failures.
