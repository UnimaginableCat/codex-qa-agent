# Variables And Status

## Scenario Variables DSL

Variables must be machine-readable. Supported forms:

- `name = env:ENV_NAME`
- `name = generated:run_suffix`
- `name = generated:run_id`
- `name = generated:timestamp_suffix`
- `name = generated:uuid`
- `name = template:AUTOTEST {{run_suffix}}`
- `name = derived:run_suffix|lower`
- `name = derived:raw_name|trim|upper`
- `name = derived:raw_integer|int`
- `name = literal:Fixed literal`

Use a raw variable plus `|int` when an env-backed or literal value must be sent as a JSON number:

- `price_list_id_raw = env:PRICE_LIST_ID`
- `price_list_id = derived:price_list_id_raw|int`

The `int` transform accepts a base-10 integer. Put it last when the final value must remain numeric. A non-integer source blocks variable resolution before the API or DB step runs.

Do not treat prose as a value. Examples that must block:

- `email_suffix = the lowercase form of run_suffix`
- `run_suffix generated dynamically`
- `display_name = Fixed literal without literal prefix`

Resolution priority:

1. captured values from prior steps
2. explicit scenario variables
3. environment-backed values
4. generated runtime values
5. derived/template variables

Never print raw secret values.

## Legacy Status Priority

Use the runner's projected final status unless there is strong evidence the runner is incorrect.

Priority:

1. `ERROR`
2. `BLOCKED`
3. `FAIL`
4. `PASS`

Classification:

- `PASS`: executed and matched expectations
- `FAIL`: executed but expectations were not met
- `BLOCKED`: missing env/config/auth/access/dependency or unavailable required setup
- `ERROR`: tool/runtime/parsing/unexpected technical failure

## Guided Termination Interpretation

Do not infer lifecycle from status alone.

Use:

- `continuation_state` for paused/resumed/terminal
- `details.run_termination` for completed/failed/blocked/errored/paused/aborted/partial semantics
- `operator_state` for active decision, actions, required inputs, and resume instructions
- `decision_resolution` for selected action and resume strategy after resume
