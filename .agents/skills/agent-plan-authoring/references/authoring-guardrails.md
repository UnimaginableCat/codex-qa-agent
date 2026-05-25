# Authoring Guardrails

Read this reference only when authoring a broad runnable bundle, fixing authoring diagnostics, or deciding whether a case is safe to promote downstream.

## Evidence Contracts

- Route paths must be the final path after `API_BASE_URL`, not app-local framework paths. Use `runtime_path_evidence` from root URLConf, gateway routing, OpenAPI, or a runtime smoke check.
- Action-like routes such as search, calculate, export, download, report, approve, archive, or duplicate need method-capable evidence from handlers, controllers, services, or tests. URL/router files prove mounting, not HTTP method.
- Request bodies need field-specific schema evidence for every authored top-level key. Generic phrases such as `uses serializer` are not enough.
- Binary endpoints should assert `response body exists` unless the scenario includes executable content inspection.

- Quote YAML scalar values that contain `:`, `{`, `}`, `#`, or inline evidence such as `path.py: SymbolName`. A parser `BLOCKED` result from unquoted evidence is an authoring error, not a reason to continue.

## Runnable DSL

- Use only supported API expectations: `response JSON exists`, `response body exists`, `response JSON is an array`, `response contains field \`id\``, `response \`status\` = \`ACTIVE\``, `response \`createdAt\` is not null`, and length checks.
- Use only supported DB expectations: `one row exists`, `no rows exist`, `` `status` = `ACTIVE` ``, and null/not-null checks.
- Do not author prose checks such as `response contains formula item with ...`, `response items include ...`, `response indicates ...`, or `response email is null or omitted`.
- If the desired assertion cannot be expressed, preserve intent with a supported JSON path assertion, array membership support, or DB verification. Do not weaken to `response body exists` unless body existence is the behavior under test.
- For indexed response paths, prove every indexed collection level with a length assertion or structured fixture/data contract.

## Variables And Auth

- Keep variables in first-class `scenario_variables[]` using supported prefixes: `env:`, `generated:`, `template:`, `derived:`, or `literal:`.
- Quote whole YAML variable entries, for example `"name = template:qa-{{run_suffix}}"`.
- Separate submitted values from normalized expected values, for example `submitted_email` and `expected_email = derived:submitted_email|lower`.
- Use `defaults.actor`, `metadata.default_actor`, `setup[].actor`, and `execute.actor` for actor profiles. Do not encode actor selection in free-form prose.
- Do not author bearer headers for projects that use basic auth profiles; use `defaults.auth: basic` and actor-scoped env keys.

## State, Persistence, And Identity

- Mutating cases need persisted-state verification unless the operation is intentionally read-only.
- Do not solve persisted-state diagnostics by changing an entity `id_field` to whichever variable is available. Fix captures, DB params, `scoped_by`, or entity `key_fields`.
- Do not weaken relationship DB checks. If a relationship should prove `(item_id, variable_id)`, add the missing capture/setup rather than checking “some row exists”.
- Created ids must use distinct captures such as `created_*`; never overwrite fixture variables such as `price_list_id = env:PRICE_LIST_ID`.
- Model permission/access relationships with canonical ids or natural `key_fields`, not actor GUIDs as fake entity ids.

## Reusable DB Verifications

- A reusable DB verification must be true for every case that references it. If two cases use different formulas, do not reuse one verifier with hardcoded row content such as `` `code` starts with `reserve` ``.
- Formula-link verifications must match the formula-specific non-system variable set. For `base_qty * thickness_cm / 100 * (1 + reserve_percent / 100)`, expect `thickness_cm` and `reserve_percent`; for `base_qty * thickness_cm / 100`, expect only `thickness_cm`. Exclude system variables such as `base_qty`.
- Do not combine `one row exists` with SQL that can return one row per related variable unless the SQL filters to exactly one expected relation. Use a case-specific verifier, a parameterized expected variable code, or separate checks for each expected variable.
- Do not change relationship entity identity to make a generic verifier pass. Keep the relationship's real id or natural key and repair captures, params, and expected outcomes.

## Permissions And Roles

- Role/actor coverage must be structured: `metadata.required_roles`, `metadata.required_actors`, `metadata.default_actor`, `execute.actor`, or structured coverage claims. Titles, objectives, and tags do not count.
- Permission grants/revokes must bind the target subject to the actor that later executes the gated action. Do not grant the first row from a management list unless evidence proves it belongs to the actor credentials.
- Negative/default permission cases must be self-contained: reset/revoke or baseline-check the effective state before expecting denial. A bare `403` does not prove permission intent.

## Lifecycle

- Same-state lifecycle behavior needs explicit operation-inventory semantics: `target_state`, `same_state_behavior`, `same_state_status`, and `same_state_evidence`.
- Determine same-state behavior from the full request path, including controller guards, not only from the domain method.
- If same-state behavior is `idempotent_success`, author a repeated-call success case with persisted-state verification.

## Validation And Readiness

- Missing env-backed variables are preflight/readiness blockers, not permission to remove variables, request fields, setup, assertions, or DB verification.
- Open questions that must be resolved “before promoting”, “before running”, or “before execution” are blocking. Resolve them, defer the affected case, or report the blocker.
- Generated scenarios must be independent. Do not rely on another scenario running first unless the runner has an explicit dependency contract.
- Do not delete coverage cases just to make validation pass. Repair evidence/setup or keep the case deferred/blocked with the reason.
