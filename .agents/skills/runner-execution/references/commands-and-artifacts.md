# Commands And Artifacts

## CLI Commands

- Auto run: `python -m tools.scenario_runner.cli --scenario <scenario.md>`
- Guided run: `python -m tools.scenario_runner.cli --scenario <scenario.md> --mode guided`
- Inspect pause: `python -m tools.scenario_runner.cli --inspect-pause <pause-state.json>`
- Resume: `python -m tools.scenario_runner.cli --resume <pause-state.json> --action <action_id>`

Use `py -m ...` on Windows only when `py` resolves to Python 3.14+ and the local venv does not.

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
