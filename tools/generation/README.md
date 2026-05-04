# Generation Pipeline Foundation

Phase 1 generation artifacts are isolated from `scenario_runner` artifacts.

Canonical request bundle:

```text
artifacts/agent/generation/<run_id>/
  manifest.json
  authoring-plan.yaml
  agent-plan.json
  context.json
  source-input.json
  normalized-source.json
  normalized-plan.json
  traceability-map.json
  diagnostics.json
  scenario-drafts/
    <draft>.md
  scenario-render-result.json
  scenario-parse-results.json
  unsupported-checks.json
  deferred-items.json
  promotion-result.json
  summary.json
```

Treat this bundle as the single source of truth for one generation request.

Skill routing:

```text
broad workspace request -> qa-entrypoint
coverage decomposition / authoring DSL -> agent-plan-authoring
compile / generate / render / review / promote / validate -> test-plan-generation
```

Preferred DSL flow:

```text
authoring-plan.yaml
-> compiler
-> agent-plan.json
-> GenerateTestPlanUseCase
-> NormalizedTestPlan
```

When scaffolded through the CLI, `authoring-plan.yaml` lives inside the generation run bundle at
`artifacts/agent/generation/<run_id>/authoring-plan.yaml`.

`defaults.actor` in `authoring-plan.yaml` is not just descriptive metadata. It compiles into a
rendered scenario variable `actor = literal:<value>` and acts as an execution profile selector for
actor-scoped API/DB env keys such as `API_BASE_URL__API_CLIENT` or `DATABASE_URL__API_CLIENT`.

`defaults.headers` in `authoring-plan.yaml` is the preferred way to apply shared custom request
headers across authored API and workflow requests. It is especially useful for env-backed headers
such as `X-Leadflow-Internal-Token: "{{internal_api_token}}"`. Case-level or entity-operation
headers override the same keys from `defaults.headers`.

For projects that use basic auth, set `defaults.auth: basic` and use actor-scoped env profiles
instead of authored `Authorization` headers. Role-specific cases can set `metadata.default_actor`
to values such as `founder` or `partner`; rendered scenarios then use `actor = literal:<role>` and
runtime selects `API_AUTH_TYPE__<ROLE>`, `API_USERNAME__<ROLE>`, and `API_PASSWORD__<ROLE>`.

Avoid turning every actor or company member GUID into an env prerequisite. Env should carry
credentials and stable root fixtures such as `company_guid` or `price_list_id`; internal role
identity values such as `company_member_guid` or `user_guid` should usually be discovered by an
authored workflow setup API/DB step and captured for later steps.

This lint is policy-driven through `metadata.identity_resolution`. By default authoring validation
warns on env-backed `company_member_guid` / `user_guid` style variables, but a project can set
`allow_env_identity_variables` with `justification`, or use `stable_env_fixtures`,
`discourage_env_identity`, `env_identity_name_patterns`, or `disable_default_env_identity_patterns`
when its fixture model is different. To make this a blocking contract, set
`metadata.contracts.identity.env_backed_role_identity: disallow`.

For binary/download endpoints such as PDF or Excel export, assert `HTTP 200` plus
`response body exists`. Do not assert `response JSON exists` unless the endpoint actually returns a
JSON object or array. A binary smoke assertion does not prove masking or leak prevention; keep that
claim out of the objective unless an executable content inspection is authored.

Boundary and lifecycle prose checks are also policy-driven. Objective text such as "longer than
255", "greater than 100", "negative offset", or "zero limit" is linted against authored literals as
a warning by default; set `metadata.contracts.boundary.require_literal_boundary_match: true` only
when that prose-to-request match is a strict authoring contract. Same-state lifecycle inference is a
warning when route semantics are missing; set route `same_state_contract_required: true` in
`operation-inventory.yaml` when missing `target_state`, `same_state_behavior`, or
`same_state_status` should block.

`entities.<entity>.id_field` is now executable authoring contract too. It names the canonical entity
identity variable used across setup chains and persisted-state templates, for example `user_id`.
For natural-key entities, declare `key_fields` in `entity-inventory.yaml`; synced authoring plans
can then scope persisted-state checks by all declared key fields instead of inventing a fake
single-field `id_field`. The entity-inventory validator applies a configurable warning-only
`metadata.identity_field_policy` for suspicious identity-like `id_field` values; use
`allow_id_fields` for documented exceptions, override `suspicious_id_field_patterns` for a
project's own actor/relationship identifiers, or set `enforcement: error` for an explicit strict
contract.

Prose remains a fallback/bootstrap path:

```text
prose -> prose normalizer -> NormalizedTestPlan
```

For true end-to-end coverage inside one case, use `workflow_steps[]` on
`AgentPlannedTestCaseInput`. If that workflow includes successful state-changing API operations,
add persisted-state verification with case-level `db_verification` or a `db` workflow step.

Authoring helper workflow:

```text
qa-entrypoint
-> agent-plan-authoring
-> author or refine authoring-plan.yaml
-> test-plan-generation
-> validate / compile / generate
```

Preferred CLI flow

Authoring-plan scaffold:

```powershell
<project-venv-python> -m tools.generation.cli `
  --init-authoring-plan `
  --output artifacts/agent/generation `
  --source-id users-api `
  --project code/demo `
  --name "Users API" `
  --goal "Cover user API behavior."
```

The scaffolded bundle now includes three authoring-stage files:

- `authoring-plan.yaml`
- `entity-inventory.yaml`
- `operation-inventory.yaml`

Recommended order for broad controller coverage:

1. fill `entity-inventory.yaml` with entities, states, normalized fields, and auth/header contract
2. fill `operation-inventory.yaml` with setup operations, effect states, routes, and expected HTTP codes
3. run `--sync-authoring-plan` to hydrate repeated `authoring-plan.yaml` structure from inventories
4. write final cases in `authoring-plan.yaml`

Use strict sequential authoring for broad coverage. Fill and validate one stage before editing the
next one; do not substantially rewrite all three staged files in the same authoring pass.
DB verification `scoped_by` can be a single field or a YAML array for composite natural keys, and
each scoped field must be present in the verification `params`.

Stage-oriented commands are available when the bundle already exists or only one stage file needs
to be scaffolded or validated:

- `--init-entity-inventory`
- `--validate-entity-inventory`
- `--init-operation-inventory`
- `--validate-operation-inventory`
- `--init-authoring-plan`
- `--sync-authoring-plan`
- `--validate-authoring-plan`
- `--validate-authoring-bundle`

Recommended managed-bundle walkthrough:

```powershell
# stage 1
<project-venv-python> -m tools.generation.cli `
  --init-entity-inventory `
  --output artifacts/agent/generation/<run_id>

<project-venv-python> -m tools.generation.cli `
  --validate-entity-inventory `
  --entity-inventory-file artifacts/agent/generation/<run_id>/entity-inventory.yaml `
  --output-format text

# stage 2
<project-venv-python> -m tools.generation.cli `
  --init-operation-inventory `
  --output artifacts/agent/generation/<run_id>

<project-venv-python> -m tools.generation.cli `
  --validate-operation-inventory `
  --operation-inventory-file artifacts/agent/generation/<run_id>/operation-inventory.yaml `
  --output-format text

# stage 3
<project-venv-python> -m tools.generation.cli `
  --sync-authoring-plan `
  --path artifacts/agent/generation/<run_id> `
  --output-format text

# stage 4
<project-venv-python> -m tools.generation.cli `
  --validate-authoring-plan `
  --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml `
  --output-format text

# final gate before compile/generate
<project-venv-python> -m tools.generation.cli `
  --validate-authoring-bundle `
  --path artifacts/agent/generation/<run_id> `
  --output-format text
```

For managed bundles, validate and compile now cross-check `authoring-plan.yaml` against both
inventories. Missing or contradictory entity names, operations, routes, status codes, or workflow
precondition states are blocking authoring diagnostics rather than downstream surprises.

Typical authoring pattern for custom internal-token headers:

```yaml
defaults:
  environment: env/demo.env
  headers:
    X-Leadflow-Internal-Token: "{{internal_api_token}}"
  scenario_variables:
    - "internal_api_token = env:INTERNAL_API_TOKEN"
```

Quote each YAML `scenario_variables` entry as one string and write source prefixes without a space
after the colon, for example `"display_name = template:Invalid Update {{run_suffix}}"`.
Unquoted `template: value` entries are parsed by YAML as maps instead of strings.

When a target API has domain-specific field formats, record them declaratively in
`operation-inventory.yaml` instead of adding controller-specific validation code:

```yaml
entity_operations:
  - entity: user_identity
    operation: link_telegram
    route:
      method: POST
      path: /api/internal/v1/users/{{user_id}}/identities
    request_constraints:
      - field: subject
        format: numeric_string
        when:
          provider: TELEGRAM
```

For generated digits-only values, use `generated:numeric_suffix`:

```yaml
defaults:
  scenario_variables:
    - "numeric_suffix = generated:numeric_suffix"
    - "telegram_subject = template:700{{numeric_suffix}}"
```

When DB expectations compare numeric-looking generated values against string columns, declare
`column_types` on the DB verification and quote the placeholder inside the expected string:

```yaml
db_verifications:
  - entity: user_identity
    operation: verify_telegram_identity
    column_types:
      subject: string
    expected_outcomes:
      - '`subject` = `"{{telegram_subject}}"`'
```

Authoring-plan validate-only:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-authoring-plan `
  --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml `
  --output-format text
```

Authoring-plan compile:

```powershell
<project-venv-python> -m tools.generation.cli `
  --compile-authoring-plan `
  --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml `
  --output artifacts/agent/generation `
  --output-format text
```

For managed staged bundles, do not call compile or direct generation before `--validate-authoring-bundle`
passes.

Direct generation from authoring-plan:

```powershell
<project-venv-python> -m tools.generation.cli `
  --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml `
  --workspace-root .
```

Compiled bundle flow

Validate compiled bundle:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --output-format text
```

Generate from compiled bundle:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root .
```

Draft scenario rendering preview:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/<run_id>/agent-plan.json `
  --workspace-root . `
  --render-drafts
```

Rendering is conservative: it emits parser-validated markdown previews only for cases with authored
route details (`planned_route`) or complete `workflow_steps[]`. Unsupported cases are written to
deferred/unsupported artifacts. No scenario execution, compile, preflight, API workflow, or DB
workflow is triggered.

When rendered drafts include `actor = literal:<value>`, downstream execution uses that value to
select actor-scoped env profiles before falling back to base `API_*` or `DATABASE_*` keys.

Review and promotion:

```powershell
<project-venv-python> -m tools.generation.cli `
  --review-drafts `
  --run-id <generation-run-id> `
  --workspace-root .

<project-venv-python> -m tools.generation.cli `
  --promote-draft `
  --run-id <generation-run-id> `
  --draft-id draft-tc-001 `
  --workspace-root . `
  --target-dir scenarios/generated

<project-venv-python> -m tools.generation.cli `
  --promote-all-drafts `
  --run-id <generation-run-id> `
  --workspace-root . `
  --target-dir scenarios/generated

<project-venv-python> -m tools.generation.cli `
  --promote-all-drafts `
  --run-id <generation-run-id> `
  --workspace-root . `
  --target-dir scenarios/generated `
  --purge-target-dir

<project-venv-python> -m tools.generation.cli `
  --validate-scenario-dir `
  --path scenarios/generated/<source>-<run_id> `
  --mode compile `
  --output-format text
```

Promotion is explicit, never overwrites existing files, and writes `promotion-result.json` under the
generation artifact bundle. When using the default `scenarios/generated` root, promoted drafts are
written under a run-scoped subdirectory such as `scenarios/generated/<source>-<run_id>/`. Use
`--purge-target-dir` only for deliberate rerender/re-promote cycles when the resolved target directory
should be deleted before writing the refreshed scenario set.

Use `--validate-scenario-dir --mode compile` as the normal post-promotion gate when you want one
summary verdict for a whole promoted scenario directory without writing shell loops.

Low-level escape hatches

Use these only for manual repair, debugging, or explicit direct control. They are not the default
skill-routed path.

CLI scaffold:

```powershell
<project-venv-python> -m tools.generation.cli `
  --init-agent-plan `
  --output artifacts/agent/generation `
  --source-id users-api `
  --project code/demo `
  --name "Users API" `
  --goal "Cover user API behavior."
```

Fallback prose generation:

```powershell
<project-venv-python> -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user" `
  --workspace-root .
```
