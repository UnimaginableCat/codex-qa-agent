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
understand scope -> define entities/templates -> author cases -> validate authoring-plan -> stop
```

Default completion point:

- `authoring-plan.yaml` exists or was updated
- when scaffolded from CLI, it lives under `artifacts/agent/generation/<run_id>/authoring-plan.yaml`
- `--validate-authoring-plan` was run
- authoring-level diagnostics were resolved or explicitly reported
- downstream compile/render/promote work is left to `test-plan-generation`

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
- Use `defaults.scenario_variables[]` for plan-wide variables and `cases[].scenario_variables[]` for case-local variables.
- Keep variable definitions in first-class `scenario_variables` fields. Do not hide them under `metadata`.
- For controller or endpoint full-coverage plans, prefer API and workflow cases plus persisted-state DB verification inside those cases.
- Do not add standalone schema-readiness `db-check` cases by default when the expected downstream path includes render, review, and promote.
- Use standalone `db-check` only when the user explicitly asks for schema or infrastructure verification, or when the workflow is expected to stop at authoring or compile instead of promoted runnable scenarios.
- Do not rely on the compiler to invent SQL, routes, or capture targets.

## Strict DSL Gate

Before writing a broad full-coverage plan, make the first `1-2` cases compile-safe in your head:

- API expectations must use supported patterns such as:
  - `HTTP 200`
  - `response JSON exists`
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
  - `run_suffix = generated:run_suffix`
  - `internal_api_token = env:INTERNAL_API_TOKEN`
  - `primary_email = template:autotest.{{run_suffix}}@example.com`
  - `normalized_email = derived:primary_email|lower`

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
- Validate authoring DSL:
  `<venv-python> -m tools.generation.cli --validate-authoring-plan --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml --output-format text`
- Compile to managed bundle:
  `<venv-python> -m tools.generation.cli --compile-authoring-plan --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml --output artifacts/agent/generation --output-format text`
- Generate downstream plan directly:
  `<venv-python> -m tools.generation.cli --authoring-plan-file artifacts/agent/generation/<run_id>/authoring-plan.yaml --workspace-root .`

Use only the validate step by default inside this skill. Compile/generate commands are downstream handoff points unless the user explicitly asks to continue.

If validation fails on expectation syntax, rewrite the authoring DSL itself. Do not keep unsupported phrasing and hope downstream render/review will compensate.

# Guardrails

- Do not write full `agent-plan.json` as the primary artifact.
- Do not perform render, review, promote, or scenario validation from this skill unless the user explicitly asks to continue into downstream work.
- Do not compensate for missing templates, SQL, or capture targets by writing prose placeholders that the compiler must guess.
- Do not treat a standalone schema `db-check` as part of the default controller-coverage recipe when promoted markdown scenarios are the expected downstream output.

# References

- `references/authoring-dsl.md`
- `assets/examples/users-authoring-plan.yaml`
