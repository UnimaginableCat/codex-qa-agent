# Commands And Artifacts

## CLI Commands

- Auto run: `<venv-python> -m tools.scenario_runner.cli --scenario <scenario.md>`
- Guided run: `<venv-python> -m tools.scenario_runner.cli --scenario <scenario.md> --mode guided`
- Inspect pause: `<venv-python> -m tools.scenario_runner.cli --inspect-pause <pause-state.json>`
- Resume: `<venv-python> -m tools.scenario_runner.cli --resume <pause-state.json> --action <action_id>`

Run these commands through the project/workspace venv interpreter. Do not use system `python` or `py` unless the user explicitly authorizes a non-venv fallback.

## Auto Output

Auto mode returns the legacy-compatible summary payload at the top level. Expect fields such as:

- `final_status`
- `message`
- `run_state_dir`
- `artifact_dir`
- `report_path`
- `steps`
- `continuation_state`
- `details.run_mode`
- `details.run_termination`
- `details.legacy_status_projection`

## Guided Output

Guided/manual mode returns:

- `summary`: the same summary payload as auto mode
- `operator_state`: operator-facing read model

Inspect `operator_state` before deciding next action. Important fields:

- `resumable`
- `pause_state_path`
- `active_decision_point`
- `active_diagnostic`
- `available_actions`
- `recommended_action_id`
- `required_inputs`
- `resume_instructions`
- `run_termination`

## Artifacts To Inspect

Minimum:

- `.codex-qa/runs/<run-id>/summary.json`
- `artifacts/agent/<scenario-slug>-<run-id>/report.md`

When relevant:

- `.codex-qa/runs/<run-id>/pause-state.json`
- `.codex-qa/runs/<run-id>/journal.jsonl`
- `artifacts/agent/<scenario-slug>-<run-id>/manifest.json`
- `artifacts/agent/<scenario-slug>-<run-id>/steps/<step-id>/input.json`
- `artifacts/agent/<scenario-slug>-<run-id>/steps/<step-id>/raw-result.json`

Inspect these files as generated evidence. Do not edit `summary.json`, `report.md`, `journal.jsonl`, `pause-state.json`, manifests, or raw step artifacts unless the user explicitly asks to repair artifacts.

Guided/manual interaction is valid only when output/artifacts expose a real `operator_state`, `pause_state_path`, and active decision point. If the run is terminal without pause-state, report the terminal status and do not ask for an action.

## Final Response Checklist

Include:

- scenario name/path
- target project under `code/`
- run mode
- final status
- continuation state
- run termination kind/reason if available
- active decision and actions if paused
- failed/blocked steps
- summary/report/pause-state paths
- interpreter used
- network/dependency caveats if they affected execution
