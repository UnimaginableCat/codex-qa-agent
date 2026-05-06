---
name: agent-plan-authoring
description: Author compact LLM-facing test-plan DSL files that compile deterministically into AgentTestPlanInput without exposing the full internal generation contract.
---

# Purpose

Use this skill when the task is to think like a QA author and produce or refine compact authoring DSL,
not to render drafts or promote scenarios.

Use this as the primary skill for requests such as:

- generate a test plan
- decompose controller or feature coverage
- author CRUD, workflow, validation, or negative-path coverage
- refine authored coverage after authoring-level diagnostics

This skill owns only:

- scope decomposition
- entity and operation selection
- compact case authoring
- authoring-level defect fixing

This skill does not own:

- downstream `NormalizedTestPlan` assembly
- draft rendering
- review
- promotion
- scenario execution

# Contract

Author `authoring-plan.yaml`, not full `agent-plan.json`.

In this workspace, an authored "test plan" is a machine-readable staged generation bundle. Do not
complete an authoring request by creating or updating a prose Markdown file such as
`docs/*TEST_PLAN*.md`, even if the target project already has documents in that style, unless the
user explicitly asks for documentation-only output. The normal output path is
`artifacts/agent/generation/<run_id>/authoring-plan.yaml` with the staged inventories.

Required top-level fields:

- `version`
- `source_id`
- `project`
- `title`
- `goal`
- `scope`
- `entities`
- `cases`

Required per case:

- `id`
- `kind`
- `objective`
- `state_change`
- `execute.route` for `api` and `workflow`
- `oracle`

Supported case kinds in MVP:

- `api`
- `workflow`
- `db-check`

# Lifecycle

```text
understand scope -> inventory entities/states -> inventory operations/status contracts -> author cases -> validate staged bundle -> stop
```

Before running any `tools.generation` CLI command, resolve and use the workspace-root venv interpreter. Check only root-level venv candidates such as `.venv314/Scripts/python.exe`, `.venv/Scripts/python.exe`, `.venv314/bin/python`, and `.venv/bin/python`. Do not use `code/<project>/.venv*`, `python`, `python3`, `py`, or `uv run` as probes before checking the workspace venv. A root venv created by tools such as `uv` may have a `python` executable that resolves to an external base interpreter path; do not declare it non-workspace solely from `readlink`/resolved executable location. Trust the workspace CLI guard result, which validates the active venv prefix. If no workspace-root venv interpreter can run the generation CLI, report authoring tooling readiness as `BLOCKED`; use any non-workspace interpreter only after explicit user authorization.

Default completion point:

- `authoring-plan.yaml` exists or was updated
- `entity-inventory.yaml` and `operation-inventory.yaml` were reviewed or updated when the bundle was scaffolded
- when scaffolded from CLI, it lives under `artifacts/agent/generation/<run_id>/authoring-plan.yaml`
- no project-local `docs/*.md` file is used as the primary deliverable unless the user explicitly requested a prose-only documentation artifact
- `--validate-authoring-bundle --path artifacts/agent/generation/<run_id>` was run for managed bundles
- `--validate-authoring-plan` may still be used as a local authoring check, but it is not the final staged handoff gate for managed bundles
- authoring-level diagnostics were resolved or explicitly reported
- the final bundle gate must have explicit evidence: stdout must show `Status: PASS` or JSON must contain `status=PASS`
- if any validation command returns no stdout or an unreadable/truncated payload, do not infer success from command completion; rerun with `--output-format json` or read the persisted result artifact before reporting PASS
- downstream compile/render/promote work is left to `test-plan-generation`
- final responses for this skill must explicitly say that the result is an authoring bundle only:
  no runnable scenario drafts were rendered, no scenarios were promoted, and downstream generation
  requires `test-plan-generation` or an explicit compile/render command

# Invocation

The normal user-facing entry point is `qa-entrypoint`.

Call this skill directly only when the routing decision is already explicit and the request should
start inside the authoring branch rather than being classified first.

# Authoring Rules

- Keep the DSL compact and declarative.
- Use YAML as the default authoring format.
- Do not write the full internal `AgentTestPlanInput`.
- Use only supported expectation DSL. Do not invent natural-language checks that "sound right" but are not compile-safe.
- Use `setup[]` only on `workflow` cases.
- Resolve reusable setup and persisted-state templates through `entities.<entity>.operations.<name>`.
- Use deterministic `oracle.status_code`, `oracle.business_checks`, `oracle.captures`, and `oracle.persisted_state`.
- Use `defaults.environment` when one env file should flow into rendered scenario `## Environment`.
- Use `defaults.actor` when a stable execution actor should flow into rendered scenario variables as `actor = literal:<value>` and select actor-scoped API/DB env keys such as `API_BASE_URL__API_CLIENT` or `DATABASE_URL__API_CLIENT`.
- Use `defaults.headers` for shared request headers that should be applied across authored API and workflow requests.
- For basic auth, use `defaults.auth: basic` plus actor-scoped env profiles such as `API_AUTH_TYPE__FOUNDER=basic`, `API_USERNAME__FOUNDER`, and `API_PASSWORD__FOUNDER`. Do not author `Authorization: Bearer {{...}}` headers or `*_token` variables for projects that authenticate with basic auth.
- When cases need different role credentials, set `metadata.default_actor` per case, for example `founder`, `manager`, or `partner`; this renders a case-specific `actor = literal:<role>` variable and selects matching actor-scoped env keys.
- For true multi-actor workflows, use `setup[].actor` for setup operations that must run under a different role and `execute.actor` for the main action when needed. Rendered workflow steps include `Actor: <role>`, parser/preflight/runtime preserve it, and runtime uses the step actor before falling back to the scenario-level `actor` variable.
- For PDF, Excel, export, or other binary endpoints, use `response body exists` rather than `response JSON exists`; binary responses are not JSON assertions. Do not claim leak prevention or masking for a binary endpoint unless the plan includes an executable content inspection or a narrower smoke-test objective.
- Never infer the HTTP method for PDF, Excel, export, download, report, calculate, search, or other action-like endpoints from the route name. Record the method from method-capable evidence: handler/controller/view/action implementation or tests. Operation inventories require structured `method_evidence` for action-like paths even when `metadata.contracts.routes.method_evidence_required` is not enabled; broad method evidence can still be required for all routes with that contract switch. Route mapping sources such as URLConf/router files prove mounting, not whether the handler implements GET, POST, or another method. Free-form strings such as `search view is POST` or dictionaries that only repeat `method: POST` are not evidence. `source_role: method_handler` or equivalent capability metadata is only valid for non-mapping implementation files; it must not be used to make known mapping files such as `urls.py`, `routes.py`, `router.*`, or `routing.*` count as method evidence. If the method cannot be proven, keep the case deferred/open rather than guessing `GET` or `POST` for an action-like path.
- For runnable API scenarios, author route paths as the final request path after `API_BASE_URL`, not as app-local framework routes. Do not treat `apps/<app>/urls.py` as sufficient evidence for the runtime path. Prove the mounted/external path with root URLConf, API gateway/deployment routing, OpenAPI/schema, or a runtime smoke check. In `operation-inventory.yaml`, enable `metadata.contracts.routes.runtime_path_evidence_required: true` and add structured `runtime_path_evidence` on each route, for example:
  ```yaml
  runtime_path_evidence:
    source_ref: code/<project>/project/urls.py
    runtime_path: /api/v1/price-list/{{price_list_id}}/permissions/
    evidence: Root URLConf mounts price-list URLs under /api/v1/ after API_BASE_URL.
  ```
  The authored `path` must match this runtime path. If only app-local evidence is available, keep the route unresolved instead of promoting `/price-list/...` guesses.
- Do not require operators to hand-populate role identity GUIDs such as `PRICE_LIST_PARTNER_MEMBER_GUID`, `PRICE_LIST_CUSTOMER_MEMBER_GUID`, or `*_USER_GUID` when the scenario already has actor credentials. Prefer a workflow setup step that discovers the GUID through a permissions API response or read-only DB lookup and captures it into `company_member_guid` or `user_guid`. Env should hold credentials and stable fixture roots such as `company_guid` or `price_list_id`, not every user's internal GUID.
- If a project really needs env-backed identity GUIDs, document that in `metadata.identity_resolution` with `allow_env_identity_variables` plus `justification`, or with `stable_env_fixtures`, `discourage_env_identity`, `env_identity_name_patterns`, or `disable_default_env_identity_patterns`; do not rely on implicit naming assumptions.
- Use `defaults.scenario_variables[]` for plan-wide variables and `cases[].scenario_variables[]` for case-local variables.
- Keep variable definitions in first-class `scenario_variables` fields. Do not hide them under `metadata`.
- In YAML, quote the whole `scenario_variables` entry and write source prefixes without a space after the colon:
  use `"display_name = template:Invalid Update {{run_suffix}}"`, not `display_name = template: Invalid Update {{run_suffix}}`.
  Unquoted `template: value` entries are parsed by YAML as maps instead of strings.
- For normalized fields such as `email`, separate submitted input variables from expected output variables. Prefer patterns like `submitted_email` plus `expected_email = derived:submitted_email|lower` instead of reusing one placeholder in both request and expectation.
- Prefer `defaults.headers` plus env-backed variables for custom tokens such as `X-Leadflow-Internal-Token`; do not encode custom header semantics as fake auth types.
- For controller or endpoint full-coverage plans, prefer API and workflow cases plus persisted-state DB verification inside those cases. For successful `POST` routes that are intentionally read-only, such as export/download/search commands, set `state_change: read_only` and do not add fake DB checks that only prove the fixture exists.
- For visibility or masking cases, declare the claim structurally in `metadata.coverage_claims.visibility`; do not rely on objective wording to activate strict coverage gates. Include the field names, exact response paths, and whether a non-empty collection is required, for example:
  ```yaml
  metadata:
    coverage_claims:
      visibility:
        fields: [cost_price]
        response_paths: [categories.0.positions.0.cost_price]
        requires_non_empty_result: true
  ```
- For visibility or masking cases, assert the actual field behavior when the response is JSON, using the exact JSON path proven by serializer/API evidence. Do not assert root-level `response \`price\` = \`null\`` or `response \`cost_price\` = \`null\`` for price-list detail/search/template responses unless source evidence proves those fields are at response root. Prefer nested paths such as `response \`categories.0.positions.0.cost_price\` = \`null\`` plus a non-empty/index assertion like `response contains field \`categories.0.positions.0.id\`` or `response \`categories\` length >= \`1\`` when supported.
- For search/list visibility cases with `requires_non_empty_result: true`, prove that matching fixture data exists before asserting masking. Use setup that creates/discovers a matching record or an explicit structured contract such as `metadata.data_contract.non_empty_paths` / `metadata.fixture_contract.non_empty_paths` for the exact indexed response path. Strict contracts also require provenance such as `source`, `source_ref`, `evidence`, `setup_operation`, `discovery_operation`, or `db_verification`; `non_empty_paths` alone is not evidence. A plain oracle check such as `response items length >= 1` or `response contains field \`items.0.id\`` only turns missing fixture data into runtime FAIL; it does not prove readiness.
- When a workflow grants/revokes permissions for a role/principal and then executes as that actor, bind the permission subject to the actor profile. Do not grant the first captured user/member/principal id from a management list and then execute as a named actor unless metadata or setup proves that captured identity belongs to that actor credentials. This also applies when the permission effect subject is a placeholder such as `{{partner_company_member_guid}}`; the validator treats it as unbound unless the plan proves which actor owns that captured principal. Weak prose such as `partner_company_member_guid is the partner actor fixture` is not enough. Prefer capturing the current actor principal id/guid, using an actor-scoped env fixture such as `env:PARTNER_USER_GUID` with `metadata.identity_resolution` justification, or adding structured `metadata.identity_resolution.actor_binding` with `actor`, `subject_variable`, and `evidence`/`source_ref`.
- When the scope promises a role or actor matrix, declare the required roles in a machine-readable way, for example `metadata.required_roles`, `metadata.required_actors`, `metadata.coverage.required_roles`, or an explicit list-like scope item such as `roles: founder, manager, partner, member`. Do not rely on generic free-form prose like `role-based access control` or `actor permission flow`; those are coverage topics, not required role declarations.
- Every required role must be covered by structured case data: `metadata.default_actor`, `execute.actor`, `metadata.actor`/`metadata.role`, or structured `metadata.coverage_claims.*.actor` / `role`. Mentions in case `id`, `title`, `objective`, or tags do not count. If a required role is intentionally out of scope, add a structured role waiver under `metadata.coverage.role_waivers` with the reason rather than deleting the role from scope.
- If the runner cannot inspect the relevant binary/content surface, keep that as an open question or narrow the objective to a binary response smoke check.
- Treat heuristic diagnostics as review signals unless a plan or inventory explicitly enables a strict contract. Strict visibility contracts require structured `metadata.coverage_claims.visibility`; regex matches in titles/objectives stay lint-only. Other strict examples include `metadata.contracts.identity.env_backed_role_identity: disallow`, `metadata.contracts.boundary.require_literal_boundary_match: true`, `operation-inventory.yaml` route `same_state_contract_required: true`, or `metadata.identity_field_policy.enforcement: error`.
- Do not add `metadata.readiness: evidence_supported` only to silence draft review notes. If a case uses `readiness: evidence_supported`, it must also include concrete `readiness_evidence`, `evidence`, `source_evidence`, or `evidence_refs` explaining what proves the route, auth, request body, assertions, and setup are ready.
- For list/filter cases that create data in setup, assert that the created entity appears in the response when runner-supported DSL can express it, for example `array contains item with id = {{user_id}}`; do not stop at `response JSON is an array` when entity membership is the behavior under test.
- For negative validation cases, isolate one invalid field at a time. Keep other required fields valid so a `400` proves the intended validator rather than a different missing-field failure.
- For auth negative cases, do not mix invalid credentials with missing resources. Prefer a collection/list endpoint or a previously created entity so `401` is attributable to auth, not resource lookup order.
- Do not add standalone schema-readiness `db-check` cases by default when the expected downstream path includes render, review, and promote.
- Use standalone `db-check` only when the user explicitly asks for schema or infrastructure verification, or when the workflow is expected to stop at authoring or compile instead of promoted runnable scenarios.
- Do not rely on the compiler to invent SQL, routes, or capture targets.

## Staged authoring

When coverage is broad, do not jump straight to final cases in one pass.

Use strict sequential authoring. Treat each staged file as a gate, not as three files to fill in
one edit:

1. Edit only `entity-inventory.yaml`, then run `--validate-entity-inventory`.
2. Edit only `operation-inventory.yaml`, then run `--validate-operation-inventory`.
3. Run `--sync-authoring-plan` to hydrate repeated `authoring-plan.yaml` structure from the two inventories.
4. Edit only authored cases in `authoring-plan.yaml`, then run `--validate-authoring-plan`.
5. Run `--validate-authoring-bundle`.

For every validation gate, inspect an explicit status before continuing. A command that emits no
stdout is not a PASS signal. Rerun with `--output-format json` or read the corresponding generated
artifact before claiming the gate passed.

Do not fill or substantially rewrite `entity-inventory.yaml`, `operation-inventory.yaml`, and
`authoring-plan.yaml` in the same editing pass. If a later stage reveals an earlier inventory
mistake, return to that earlier file, revalidate it, then continue forward again.

Use the scaffolded bundle in this order:

1. `entity-inventory.yaml`
   - entities
   - lifecycle states
   - allowed transitions
   - normalized fields like `email`
   - shared auth/header contract
2. `operation-inventory.yaml`
   - setup operations and their effect state
   - executable setup operation templates, including route or SQL, request data, expected status, and captures needed by later workflow steps
   - explicit capture rules in the form `response.json.<field> -> <variable>`; never write bare capture targets such as `user_id`
   - controller routes
   - expected success/failure HTTP codes
   - `method_evidence` for non-obvious routes, especially export/download/action endpoints; when `metadata.contracts.routes.method_evidence_required: true` is enabled, routes without this evidence fail operation inventory validation
   - `runtime_path_evidence` for executable API routes; when `metadata.contracts.routes.runtime_path_evidence_required: true` is enabled, routes without root-mounted/external path evidence fail operation inventory validation. This evidence proves the path segment after `API_BASE_URL`; app-local `apps/<app>/urls.py` evidence alone is not valid runtime path evidence.
   - lifecycle route `target_state`
   - lifecycle route `same_state_behavior`, `same_state_status`, and `same_state_evidence` when the command can be invoked on an entity already in the target state
   - DB verification templates with SQL, params, and expected outcomes for every operation later used by `oracle.persisted_state`
   - DB verification `scoped_by` may be a single field or an explicit YAML array for composite natural keys; every scoped field must be present in `params`
   - For natural-key entities, keep the real `id_field` and declare composite identity in entity `key_fields`; do not replace `id_field` with a convenient fixture variable just to satisfy persisted-state validation
   - For permission/access/grant/override relationship entities, never set `id_field` to `member_guid`, `user_guid`, actor GUIDs, or fixture variables just to make persisted-state checks compile. Keep a canonical entity-owned id field when available; otherwise model the relationship through `key_fields` and scope DB verification with all natural-key fields.
   - If `--validate-entity-inventory` reports a suspicious identity-like `id_field` warning, review the entity model before continuing. If the project genuinely uses that field as the entity identity, document the exception in `metadata.identity_field_policy.allow_id_fields`; use `metadata.identity_field_policy.enforcement: error` only when the project explicitly wants this lint to block.
3. `--sync-authoring-plan`
   - after both inventories validate, synchronize `scope`, `entities`, reusable route operations, and DB verification templates into `authoring-plan.yaml`
   - this command does not invent final cases; it removes the need to repeat inventory facts by hand
4. `authoring-plan.yaml`
   - only after the first two files are coherent
   - author case intent, request payloads, case-local variables, and assertions that are not already sourced from inventory

Prefer explicit stage commands when the bundle already exists or when you only need one stage file:

- `--init-entity-inventory`
- `--validate-entity-inventory`
- `--init-operation-inventory`
- `--validate-operation-inventory`
- `--init-authoring-plan`
- `--validate-authoring-plan`

Before handing off to compile or downstream generation, prefer one bundle-level gate:

- `--validate-authoring-bundle --path artifacts/agent/generation/<run_id>`

This staged pass reduces common authoring failures:

- wrong setup state for workflow routes
- wrong HTTP code assumptions
- reusing submitted values as normalized expected values

In managed bundles, validation is now inventory-backed rather than inventory-adjacent:

- `authoring-plan.yaml` entities must match `entity-inventory.yaml`
- setup and persisted-state operations must match `operation-inventory.yaml`
- case routes and HTTP status codes must match `operation-inventory.yaml`
- workflow setup state must satisfy the staged precondition for the route; inferred precondition mismatches are warnings, while explicit `precondition_state` mismatches remain blocking contract failures
- when a request body needs a target member/user GUID, make the case a workflow and capture that GUID in a setup API/DB step instead of adding another env-backed `*_MEMBER_GUID`
- same-state lifecycle cases such as `archive archived`, `activate active`, or `suspend suspended` should be backed by explicit staged route semantics instead of inferred rejection assumptions; missing semantics warn by default and block only when the route declares `same_state_contract_required: true`
- route templates in `operation-inventory.yaml` must use runner placeholders such as `{{user_id}}`; do not use framework placeholders like `{userId}` in staged executable routes
- declared role/actor coverage is enforced structurally. If validation reports `authoring_scope_role_coverage_missing`, add a real case running as that role, add a structured coverage claim for that role, or add an explicit waiver. Do not satisfy the diagnostic by only mentioning the role in titles, objectives, tags, or generic scope prose.

After any edit to `operation-inventory.yaml` after `--sync-authoring-plan`, rerun:

1. `--validate-operation-inventory`
2. `--sync-authoring-plan`
3. `--validate-authoring-plan`

Do not manually patch synced route/setup/DB template sections in `authoring-plan.yaml` to compensate for an incomplete operation inventory. Fix the inventory source first, then sync again.

Do not solve a persisted-state `id_field` diagnostic by changing entity identity to whichever variable is available in a case. Fix the DB verification template, `params`, `scoped_by`, captures, or entity `key_fields` instead.

If `--sync-authoring-plan` produces `route: null`, `sql: ''`, empty `expected_outcomes`, or a capture like `response.json.user_id -> user_id` that was inferred from a bare target, treat the previous inventory stage as incomplete. Return to `operation-inventory.yaml`; do not rewrite the generated authoring plan by hand.

Do not delete coverage cases just to make validation pass. If a case cannot be expressed safely, keep the coverage item as an unresolved blocker/open question in the report, or repair the staged inventory/source evidence until the case is valid.

Open questions or `metadata.non_blocking_notes` that say something must be confirmed "before promoting", "before running", or "before execution" are blocking authoring questions. Resolve them or mark the affected cases deferred before downstream generation; do not move execution blockers into non-blocking notes and do not promote scenarios while such questions remain.

Do not author independently promoted scenarios that depend on another scenario having run first. Phrases such as "before this case runs", "grant must already be present", or "requires previous scenario" mean the case needs self-contained setup, a dedicated fixture, or an intentional deferred/open question; they are not acceptable runnable preconditions for batch execution.

For permissions coverage, do not model positive permission-gated behavior with preconfigured actors such as `editor_with_publish`, `user_with_export`, `partner_with_create`, or prose like "actor already has can_create" unless that actor is explicitly documented as a stable fixture and the limitation is recorded. Prefer a self-contained workflow: discover or create the target subject, reset or update the relevant permission/right/access state under the managing actor, verify the persisted state, execute the gated action under the affected actor, and cover revoke/denial separately. For executable positive permission-gated cases, declare `required_permission_state[]` on the case and add matching setup operation `permission_state_effects[]`; validation will block a declared required state that is not established by setup.

For permissions negative/default cases, do not assume a role fixture currently lacks overrides just because the role normally defaults to denied. Batch runs can mutate shared permission fixtures, and QA envs may already have `can_edit=true` or `can_create=true`. Declare the denied/default permission as structured data; prose in `id`, `title`, `objective`, `tags`, `oracle.business_checks`, `metadata.default_actor`, or a bare `403` status is not a permission contract. Use `metadata.coverage_claims.permissions` as either one mapping or a list of mappings with `actor`, `permission`, `expected_state`, and `expected_result`, for example:

```yaml
metadata:
  default_actor: partner
  coverage_claims:
    permissions:
    - actor: partner
      permission: can_create
      expected_state: false
      expected_result: denied
```

Make the case self-contained by resetting/revoking the relevant permission in setup, or document a stable no-override fixture contract such as `metadata.stable_permission_fixture`. Even with a stable fixture contract, add a baseline setup/read step that checks current effective permissions or the override row before the denial/default assertion; otherwise a previous run can leave the partner already granted. A baseline cannot be satisfied by a prose string or by saying another case covers it, for example `covered by pl-perm-003`; generated scenarios must be independent. If baseline evidence is stored in metadata, use a structured object with `verified: true`, an evidence field such as `setup_operation`, `route`, `query`, `source_ref`, or `assertions`, and an explicit false/absent `expected_state`. By default, structured negative/default permission claims without setup or fixture contract block validation, and stable fixture cases without structured baseline evidence also block validation. Use `metadata.contracts.permissions.negative_cases_require_state_setup: false` or `negative_cases_require_baseline_check: false` only for an intentional, documented non-runnable authoring exception.

For create workflows, never capture a newly created id/guid/uuid into a predeclared fixture or input variable such as `price_list_id = env:PRICE_LIST_ID` or `order_guid = literal:fixture-guid`. Use a distinct target such as `created_price_list_id` or `created_order_guid`, and model DB verification with that captured value or a separate `created_*` entity. Capturing `response.json.id -> price_list_id` can overwrite the stable fixture id and hide whether the DB check validated the created row or the original fixture.

For lifecycle routes, do not author same-state negative or idempotency cases until `operation-inventory.yaml` records:

- `target_state`
- `same_state_behavior`: `reject` or `idempotent_success`
- `same_state_status`
- `same_state_evidence`: the code path or test proving the behavior, for example the domain method that no-ops when current state already equals target

When a lifecycle route in `operation-inventory.yaml` has explicit same-state semantics, include the matching same-state coverage case unless it is intentionally out of scope. For example, if archive records `target_state: ARCHIVED` and `same_state_behavior: reject`, author an `archive archived` rejection case rather than covering only activate/suspend same-state calls.

Determine same-state behavior from the full request path, not from the domain method alone:

- Inspect controller/advice, handler/use-case/service precondition checks, and tests before relying on entity methods.
- If a handler enforces `precondition_state` before calling a domain method, and the target state is outside that precondition, same-state behavior is `reject` even if the domain method would no-op when called directly.
- Domain-level idempotency is valid evidence only when no earlier handler/controller guard rejects the same-state request.

If `same_state_behavior: idempotent_success`, the authoring case must be a success/idempotency case, not a rejection case:

- set `oracle.status_code` to the recorded 2xx `same_state_status`
- assert the response remains in the target state
- include `oracle.persisted_state` to verify the entity is still in the target state after the repeated call
- name/objective should say repeated or idempotent invocation, not "rejected"

## Strict DSL Gate

Before writing a broad full-coverage plan, make the first `1-2` cases compile-safe in your head:

- API expectations must use supported patterns such as:
  - `HTTP 200`
  - `response JSON exists`
  - `response body exists`
  - `response JSON is an array`
  - `response contains field \`id\``
  - `response \`status\` = \`ACTIVE\``
  - `response \`createdAt\` is not null`
- DB expectations must use supported patterns such as:
  - `one row exists`
  - `no rows exist`
  - `` `status` = `ACTIVE` ``
  - `` `email` is null ``
- `` `email` starts with `autotest.` ``
- Capture rules must use `<source> -> <variable_name>`.
- Variable rules must use supported machine-readable syntax such as:
  - `"run_suffix = generated:run_suffix"`
  - `"internal_api_token = env:INTERNAL_API_TOKEN"`
  - `"primary_email = template:autotest.{{run_suffix}}@example.com"`
  - `"normalized_email = derived:primary_email|lower"`

Do not write unsupported prose-like checks such as:

- `response error exists`
- `response JSON array exists`
- `response array contains a user with ...`
- `response indicates only suspended users can be activated`
- `response email is null or omitted`

If a desired assertion cannot be expressed in supported DSL, prefer:

- a simpler supported API assertion plus persisted-state DB verification
- or split the behavior into a workflow case with stronger DB verification

# CLI Flow

- Scaffold authoring DSL bundle:
  `<venv-python> -m tools.generation.cli --init-authoring-plan --output artifacts/agent/generation --source-id <id> --project code/<project> --name "<title>" --goal "<goal>"`
  This creates all staged files as placeholders only; do not fill them all at once.
- Scaffold or refresh entity inventory in an existing bundle:
  `<venv-python> -m tools.generation.cli --init-entity-inventory --output artifacts/agent/generation/<run_id> --source-id <id> --project code/<project> --surface "<surface>"`
- Validate entity inventory:
  `<venv-python> -m tools.generation.cli --validate-entity-inventory --entity-inventory-file artifacts/agent/generation/<run_id>/entity-inventory.yaml --output-format text`
- Scaffold or refresh operation inventory in an existing bundle:
  `<venv-python> -m tools.generation.cli --init-operation-inventory --output artifacts/agent/generation/<run_id> --source-id <id> --project code/<project> --surface "<surface>"`
- Validate operation inventory:
  `<venv-python> -m tools.generation.cli --validate-operation-inventory --operation-inventory-file artifacts/agent/generation/<run_id>/operation-inventory.yaml --output-format text`
- Sync authoring plan from staged inventories:
  `<venv-python> -m tools.generation.cli --sync-authoring-plan --path artifacts/agent/generation/<run_id> --output-format text`
- Validate authoring DSL:
  `<venv-python> -m tools.generation.cli --validate-authoring-plan --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml --output-format text`
- Validate managed staged bundle:
  `<venv-python> -m tools.generation.cli --validate-authoring-bundle --path artifacts/agent/generation/<run_id> --output-format text`
- Compile to managed bundle:
  `<venv-python> -m tools.generation.cli --compile-authoring-plan --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml --output artifacts/agent/generation --output-format text`
- Generate downstream plan directly:
  `<venv-python> -m tools.generation.cli --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml --workspace-root .`

Use only stage validation plus `--sync-authoring-plan` by default inside this skill. Compile/generate commands are downstream handoff points unless the user explicitly asks to continue.

For managed bundles, prefer this exact authoring close-out:

1. `--validate-entity-inventory`
2. `--validate-operation-inventory`
3. `--sync-authoring-plan`
4. `--validate-authoring-plan`
5. `--validate-authoring-bundle`

Treat step 5 as the required final handoff gate.

When step 5 passes, do not describe the result as runnable coverage or completed scenario
generation. Report the bundle path, stage statuses, authored/compiled case count from the
validation output, and the next handoff command when the user wants promoted scenarios.
If the bundle validation command produced no visible `Status: PASS`/JSON `status=PASS`, report the
handoff as tooling `BLOCKED` or rerun the validation instead of stating "Final bundle: PASS".

If validation fails on expectation syntax, rewrite the authoring DSL itself. Do not keep unsupported phrasing and hope downstream render/review will compensate.

# Guardrails

- Do not write full `agent-plan.json` as the primary artifact.
- Do not write Markdown documentation as the primary artifact for "generate/sоставь test plan" requests. If existing project docs appear to use Markdown test plans, treat them as source evidence only; still scaffold or update the staged authoring bundle and run its validation gate.
- Do not perform render, review, promote, or scenario validation from this skill unless the user explicitly asks to continue into downstream work.
- Do not compensate for missing templates, SQL, or capture targets by writing prose placeholders that the compiler must guess.
- Do not treat a standalone schema `db-check` as part of the default controller-coverage recipe when promoted markdown scenarios are the expected downstream output.

# References

- `references/authoring-dsl.md`
- `assets/examples/users-authoring-plan.yaml`
