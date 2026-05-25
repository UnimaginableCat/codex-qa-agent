# Generation Repair Policy

Read this reference when compile, render, review, promotion, scenario validation, or a generated scenario run exposes a defect that may require source repair.

## Source Of Truth

- Repair source generation artifacts, not promoted markdown. Prefer `artifacts/agent/generation/<run_id>/authoring-plan.yaml` and related inventories.
- Preserve author intent and oracle strength. Do not remove captures, DB scopes, relationship keys, request fields, env-backed variables, or assertions just to make a gate pass.
- Use direct `agent_plan` editing only as a low-level escape hatch for debugging or explicit manual control.

## Review And Promotion

- `validate-agent-plan` is a minimum gate, not the only gate.
- For managed staged bundles, `validate-authoring-bundle` is required before compile/generate.
- Treat `total_edit_targets > 0`, deferred execution-critical drafts, unresolved data setup, or unsupported checks as source defects to repair before promotion.
- Promotion with known gaps requires explicit operator acceptance plus the CLI confirmation flag. A request that lists `promote` is not acceptance of concrete gaps.
- Before re-promoting, check whether the run-scoped target directory already exists. Use `--purge-target-dir` only for intentional regeneration of that run.

## Common Source Defects

- Runtime `400` on action-like request bodies usually means field/schema evidence is wrong or generic. Add field-specific, schema-backed `request_body_evidence`.
- Runtime `404` with HTML/text body while base URL and auth resolved usually means the authored runtime path is wrong. Prove mounted path with `runtime_path_evidence`.
- Runtime `405` on action-like endpoints means method evidence is suspect. Prove the method from handler/controller/service/test code; router files are not method evidence.
- Prose expectations such as `contains ... with`, `items include`, or `contains variable/item with` are source defects. Rewrite as supported JSON paths, array membership support, or DB verification.
- Indexed assertions need matching non-empty collection proof for every indexed level.
- Created entity captures must not overwrite fixture variables. Use `created_*` captures and DB checks scoped to the captured id.
- Formula-link DB failures where actual rows match the formula but the scenario expected a hardcoded variable or row count are source authoring defects. Repair the source bundle with formula-specific or parameterized link verifications, then rerender, review, and re-promote.
- Do not hot-fix synced setup operations or DB templates directly in promoted markdown or synced `authoring-plan.yaml` sections. Repair the staged inventory, rerun sync if applicable, and regenerate downstream artifacts.

## Environment And Fixtures

- Preflight `BLOCKED` means readiness is missing. Report missing env files, env-backed variables, actor profiles, dependencies, or paths; do not shrink coverage to make preflight pass.
- Empty search/list visibility results are authoring defects only when the source declares a non-empty-result contract. Repair with setup, discovery, DB verification, or a structured fixture contract with provenance.
- Permission denials/defaults need executable setup or baseline checks unless a deliberately documented non-runnable exception exists.

## Runner Feedback

- Generated scenarios are runner inputs, not source artifacts. Do not hot-patch `scenarios/generated/` as the primary fix.
- If a promoted scenario fails but the failure points to source authoring, rerender, review, and re-promote after fixing the source bundle.
- If implementation evidence proves the product behavior is correct and the scenario expectation is wrong, update source authoring and rerun downstream gates.
