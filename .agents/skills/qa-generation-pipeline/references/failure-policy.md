# Pipeline Failure Policy

Read this reference when any generation, validation, promotion, or runner stage does not cleanly pass.

## Status Model

- `PASS`: stage executed and matched expectations.
- `FAIL`: stage executed, but expectations were not met.
- `BLOCKED`: config, env, auth, access, dependency, venv, or setup is missing.
- `ERROR`: CLI/runtime/parser/unexpected technical failure.

Final status priority: `ERROR` > `BLOCKED` > `FAIL` > `PASS`.

## Stop And Repair

- Failed authoring validation returns to `agent-plan-authoring`.
- Failed compile/render/review returns to the source generation bundle; do not patch generated markdown.
- Review edit targets, deferred execution-critical drafts, or non-promotable advisories block promotion unless the operator explicitly accepts the concrete gaps.
- Promotion failures or zero promoted scenarios stop the pipeline.
- Promoted scenario validation failures are repaired in source authoring unless the user explicitly asks to inspect/edit promoted markdown.

## Frequent Authoring Diagnostics

- Role coverage diagnostics require a real structured role case, a structured coverage claim, or an explicit waiver. Do not satisfy them by editing titles/objectives/tags.
- Actor identity binding diagnostics require proving the granted subject belongs to the executing actor through current-actor capture, actor-scoped env fixture evidence, or structured `metadata.identity_resolution.actor_binding`.
- Request body evidence diagnostics require field-specific, schema-backed evidence on the same evidence item that names the authored fields.
- Permission negative/default diagnostics require structured permission claims plus self-contained revoke/reset setup or executable baseline checks.
- Created-entity capture diagnostics require distinct `created_*` captures and persisted checks scoped to those captures.
- Workflow setup state mismatches require operation inventory repair unless same-state lifecycle semantics explicitly prove the mismatch is intentional.

## Promoted Validation And Preflight

- `compile_valid_but_incomplete` from env-backed inputs is not a product failure. Run preflight or report the remaining readiness gap.
- Preflight blockers are environment/readiness blockers. Do not delete env variables, request fields, setup, assertions, or DB checks to force readiness.
- If repairing validation would weaken an oracle, DB scope, relationship key, capture, or persisted-state check, stop and explain the tradeoff instead.

## Runner Results

- Guided pause: show `operator_state`, available actions, and `pause_state_path`; wait for the operator.
- Terminal `FAIL` or `ERROR`: read failed run artifacts and do targeted implementation/debug analysis before final classification unless the user requested status-only output.
- API `404` with HTML/text body and resolved auth/base URL usually means wrong authored runtime path; repair operation inventory with mounted path evidence.
- Do not classify HTTP status mismatch as product behavior or scenario defect without artifact or code evidence.
