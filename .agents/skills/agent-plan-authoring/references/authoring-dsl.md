# Authoring DSL MVP

`authoring-plan.yaml` is the LLM-facing contract for test-plan authoring.

In the managed workflow, the editable DSL source normally lives at
`artifacts/agent/generation/<run_id>/authoring-plan.yaml`.

For broad coverage work, the scaffolded bundle also includes:

- `entity-inventory.yaml`
- `operation-inventory.yaml`

These files are not compiled directly. They exist to decompose authoring before final cases are written.

MVP decisions:

- YAML first
- deterministic compiler
- no free-form setup prose
- reusable setup/persistence templates live under `entities`

Minimal shape:

```yaml
version: 1
source_id: users-controller-plan
project: code/demo-project
title: Users controller coverage
goal: Verify main CRUD and validation flows for users API

scope:
  surface: users-controller
  style: api-first
  include:
    - create user
    - get user
    - update user
    - delete user

defaults:
  environment: env/demo.env
  auth: bearer
  actor: admin-api-client
  headers:
    X-Internal-Token: "{{internal_api_token}}"
  scenario_variables:
    - "run_suffix = generated:run_suffix"
    - "internal_api_token = env:INTERNAL_API_TOKEN"

entities: {}
cases: []
```

The example actor `admin-api-client` maps to actor-scoped env keys such as
`API_BASE_URL__ADMIN_API_CLIENT` and `DATABASE_URL__ADMIN_API_CLIENT`.

If an entity defines `id_field`, treat it as the canonical variable name for that entity instance,
for example `user_id`. Setup chains should capture it before later setup operations reuse it, and
persisted-state DB templates should reference it so verification stays scoped to the authored entity.

Compiler behavior:

- expands `setup[]` via `entities.*.operations.*`
- maps compact route/oracle definitions into `AgentTestPlanInput`
- resolves persisted-state verification via entity DB templates
- carries `defaults.environment` into rendered scenario `## Environment`
- carries `defaults.actor` into rendered scenario `## Variables` as `actor = literal:<value>`
- lets a case override that actor with `metadata.default_actor`, which is useful for role-specific basic-auth env profiles
- carries `setup[].actor` and `execute.actor` into rendered workflow steps as `Actor: <value>` for multi-actor scenarios
- merges `defaults.headers` into authored API/workflow request headers, with case-level and entity-operation headers taking precedence on key conflicts
- carries first-class `defaults.scenario_variables[]` and `cases[].scenario_variables[]` into rendered scenario `## Variables`
- uses that rendered `actor` variable to select actor-scoped API/DB env keys like `API_BASE_URL__API_CLIENT` or `DATABASE_URL__API_CLIENT`, with fallback to base keys
- uses `defaults.auth` as fallback auth strategy when case/setup API auth is not authored explicitly
- runs existing `validate_agent_plan_input(...)` after compilation

For projects that use basic auth, prefer:

```yaml
defaults:
  auth: basic
cases:
- id: founder-can-read
  metadata:
    default_actor: founder
```

The rendered scenario uses `actor = literal:founder`, so runtime selects env keys like
`API_AUTH_TYPE__FOUNDER=basic`, `API_USERNAME__FOUNDER`, and `API_PASSWORD__FOUNDER`.
Do not add `Authorization: Bearer {{...}}` headers for basic-auth projects.

For grant-then-act workflows, keep the scenario self-contained instead of relying on a pre-granted
fixture actor:

```yaml
setup:
- use_entity: price_list_permission
  operation: grant_partner_edit
  actor: founder
execute:
  actor: partner
  route:
    method: PUT
    path: /api/price_list/{{price_list_id}}/update/
```

Do not make every role/member GUID a manual env prerequisite. If a scenario has actor
credentials, derive internal identifiers through executable setup:

- capture `company_member_guid` from a permissions/list API response when that response exposes it
- otherwise use a read-only DB workflow step scoped by stable fixtures and the actor's login/email
- keep env focused on credentials and stable root fixtures such as `company_guid` and `price_list_id`

Use `metadata.identity_resolution` when a project needs different rules. The default lint warns on
env-backed `company_member_guid` and `user_guid` style variables, but projects can allow a known
external GUID with an explicit justification, define their own discouraged identity patterns, or
make env-backed identity blocking through `metadata.contracts.identity.env_backed_role_identity: disallow`:

```yaml
metadata:
  identity_resolution:
    stable_env_fixtures:
    - company_guid
    - price_list_id
    allow_env_identity_variables:
    - external_customer_guid
    justification: External customer GUID is a stable public fixture owned by the test environment.
    discourage_env_identity:
    - company_member_guid
    env_identity_name_patterns:
    - "target_.*_guid$"
    disable_default_env_identity_patterns: false
```

Example shape:

```yaml
cases:
- id: founder-grants-partner-edit
  kind: workflow
  setup:
  - use_entity: price_list_permission_target
    operation: discover_partner_member_guid
  execute:
    route:
      method: POST
      path: /api/price_list/{{price_list_id}}/permissions/update/
    body:
      partners:
      - company_member_guid: "{{company_member_guid}}"
        can_edit: true
```

Recommended staged workflow:

Use strict sequential authoring. Do not fill all three staged files in one pass.

1. fill `entity-inventory.yaml`
   - entities
   - states
   - allowed transitions
   - normalized fields
   - then validate this file before editing operation inventory
2. fill `operation-inventory.yaml`
   - setup operations
   - effect states
   - route to success/failure HTTP status expectations
   - `success_status_evidence` for mutating/action-like routes; evidence must cite code/docs/tests and explicitly mention the declared HTTP status
   - lifecycle route target state
   - same-state lifecycle behavior, status, and evidence when reissuing the same command matters; set route `same_state_contract_required: true` only when missing same-state semantics should block authoring
   - DB verification templates
   - keep `id_field` as the entity-owned canonical identity; for permission override/natural-key rows, put actor/member/price-list variables in `key_fields`
   - use `metadata.identity_field_policy` only when the default identity-field lint does not fit the project; prefer `allow_id_fields` for documented exceptions and `suspicious_id_field_patterns` for project-specific actor/relationship identifiers; set `enforcement: error` only for an explicit strict contract
   - then validate this file before editing authoring plan
3. run `--sync-authoring-plan`
   - hydrate `authoring-plan.yaml` from both inventories
   - do not manually repeat inventory-backed entity/operation templates unless the sync output shows missing executable details
4. write `authoring-plan.yaml`
   - cases should reference the first two inventories instead of inventing lifecycle and status assumptions ad hoc
   - do not infer `201` from POST/create/duplicate naming; if status evidence proves `200`, author `200`
   - when a request body needs a target member/user GUID, make the case a workflow and capture that GUID in a setup API/DB step instead of adding another env-backed `*_MEMBER_GUID`. If the GUID is actor-scoped env evidence for a grant-then-act workflow, do not overwrite that same variable with `partner_permissions.0.*`, `members.0.*`, or another first-row/list capture before the grant/revoke.
   - for action-like requests with bodies, make request body evidence field-specific. Use `request_body_evidence.required`, `fields`, `properties`, or `request_constraints` to name every authored top-level body key; broad prose such as `uses serializer` is not enough, and metadata strings such as `source_ref` paths are not field evidence.
   - for response collection assertions, make response evidence field-specific. Use `response_body_evidence`, `response_schema`, `response_serializer_evidence`, route `normalized_response_fields`, or case metadata to name the exact returned field from serializer/OpenAPI evidence; `items` and `template_items` are different contracts.
   - DB verification SQL that builds expected strings with `CONCAT`, `CONCAT_WS`, or `FORMAT` must cast named params inside those functions, for example `CAST(:code AS text)` or `:code::text`
   - for masking, visibility, or leak-prevention coverage, declare the claim in `case.metadata.coverage_claims.visibility` with `fields`, `response_paths`, and `requires_non_empty_result` when the response is a collection. Regex matches in objective/title are lint-only; strict visibility gates require this structured claim plus the relevant JSON field assertion or executable content check. For nested indexed paths such as `categories.0.positions.0.price`, prove each collection level with assertions or fixture contracts for both `categories` and `categories.0.positions`.
   - for permission negative/default coverage, declare the claim in `case.metadata.coverage_claims.permissions` as either one mapping or a list of mappings with `actor`, `permission`, `expected_state`, and `expected_result` when the role/right being denied matters. Strict permission gates use structured claims and explicit fixture/setup/baseline contracts; they do not infer permission intent from prose, actor metadata, route/body context, or a bare `403` status.
   - boundary prose such as "longer than 255", "greater than 100", "negative offset", or "zero limit" is linted against authored literals as a warning by default; use `metadata.contracts.boundary.require_literal_boundary_match: true` only when this prose-to-literal check should block
   - same-state lifecycle cases such as `archive archived`, `activate active`, and `suspend suspended` should not be authored until the route inventory explicitly says whether they reject or return an idempotent success, with a code/test evidence reference. Missing semantics warn by default; route `same_state_contract_required: true` makes the inventory contract mandatory
   - idempotent same-state success cases must verify the second call's 2xx response and persisted target state after the repeated call
   - then validate this file before the bundle gate

Recommended CLI stages:

1. scaffold or refresh entity inventory
   - `--init-entity-inventory`
   - `--validate-entity-inventory`
2. scaffold or refresh operation inventory
   - `--init-operation-inventory`
   - `--validate-operation-inventory`
3. sync authoring plan from inventories
   - `--sync-authoring-plan`
4. scaffold or refine final cases
   - `--init-authoring-plan`
   - `--validate-authoring-plan`

Recommended final stage gate before compile:

- `--validate-authoring-bundle --path artifacts/agent/generation/<run_id>`

Mandatory managed-bundle sequence:

1. create or open bundle under `artifacts/agent/generation/<run_id>`
2. make `entity-inventory.yaml` valid
3. make `operation-inventory.yaml` valid
4. run `--sync-authoring-plan`
5. make `authoring-plan.yaml` valid
6. run `--validate-authoring-bundle`
7. only then hand off to compile or downstream generation

Do not treat `--validate-authoring-plan` by itself as the final gate for a managed staged bundle.

Downstream note:

- standalone `db-check` authoring cases compile correctly, but they are not the default choice for controller coverage when the next stages are `render -> review -> promote`
- current draft rendering favors authored API routes and workflow steps; a pure schema-readiness `db-check` may remain deferred instead of becoming a promoted markdown scenario
- for controller coverage, prefer API/workflow cases with persisted-state DB verification over a separate schema-readiness case unless the user explicitly asks for schema verification

Expectation syntax is strict. Author only compile-safe checks.

Supported API checks include:

- `HTTP 200`
- `HTTP 200 or HTTP 201`
- `response JSON exists`
- `response body exists`
- `response JSON is an array`
- `response contains field \`id\``
- `response \`status\` = \`ACTIVE\``
- `response \`createdAt\` is not null`
- `response \`items\` length >= 1`

Use `response body exists` for binary/download endpoints such as PDF or Excel export. Do not use
`response JSON exists` unless the endpoint actually returns a JSON object or array.

Normalized-field guidance:

- when the request intentionally sends mixed-case or padded input that the product may normalize, do not reuse the same placeholder in output expectations
- for fields like `email`, author separate variables for submitted input and expected stored/returned value
- example:
  - `"submitted_email = template:AUTOTEST.User.{{email_suffix}}@Example.COM"`
  - `"expected_email = derived:submitted_email|lower"`
  - request body: `email: "{{submitted_email}}"`
  - expectation: `response \`email\` = \`{{expected_email}}\``

Supported DB checks include:

- `one row exists`
- `no rows exist`
- `` `status` = `ACTIVE` ``
- `` `email` is null ``
- `` `created_at` is not null ``
- `` `email` starts with `autotest.` ``

Use `one row exists` only for row-specific SQL. If the query is scoped only by a parent id and can return multiple child rows, for example template variables by `template_id`, filter the expected child row or use a count/aggregate assertion instead.

Avoid unsupported prose-like checks such as:

- `response error exists`
- `response JSON array exists`
- `response array contains a user with ...`
- `response indicates ...`
- `response email is null or omitted`
- `display_name = LeadFlow User` without backticks in DB expectations

Capture syntax is strict too:

- good: `response.json.id -> user_id`
- bad: `capture response id as user_id`

Variable syntax is strict too:

- good YAML entry: `"run_suffix = generated:run_suffix"`
- good YAML entry: `"internal_api_token = env:INTERNAL_API_TOKEN"`
- good YAML entry: `"primary_email = template:autotest.{{run_suffix}}@example.com"`
- bad: `run_suffix generated dynamically`
- bad: `internal token from env`
- bad: `display_name = Fixed literal without literal prefix`
- bad YAML entry: `display_name = template: Invalid Update {{run_suffix}}`

Header guidance:

- use `defaults.headers` for shared non-secret or env-backed headers across many requests
- use per-case `execute.headers` or entity-operation `request_headers` when a header is specific to one flow
- if the same header appears in both `defaults.headers` and a case or entity operation, the more specific authored header wins
- do not invent custom `defaults.auth` values for header-based auth schemes; model them as explicit headers instead

Supported `state_change` values:

- mutating: `create`, `update`, `delete`, `mutate`
- read-only: `none`, `read_only`, `readonly`
- case ids must be unique within one authoring plan

Compiler does not:

- invent SQL
- infer missing route templates
- infer missing capture targets
- interpret broad prose as executable detail
- use `metadata.scenario_variables` as the primary authoring path; use first-class `scenario_variables` fields instead
