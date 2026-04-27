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
- Use `setup[]` only on `workflow` cases.
- Resolve reusable setup and persisted-state templates through `entities.<entity>.operations.<name>`.
- Use deterministic `oracle.status_code`, `oracle.business_checks`, `oracle.captures`, and `oracle.persisted_state`.
- Use `defaults.environment` when one env file should flow into rendered scenario `## Environment`.
- Use `defaults.actor` when a stable execution actor should flow into rendered scenario variables as `actor = literal:<value>` and select actor-scoped API/DB env keys such as `API_BASE_URL__API_CLIENT` or `DATABASE_URL__API_CLIENT`.
- Do not rely on the compiler to invent SQL, routes, or capture targets.

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

# Guardrails

- Do not write full `agent-plan.json` as the primary artifact.
- Do not perform render, review, promote, or scenario validation from this skill unless the user explicitly asks to continue into downstream work.
- Do not compensate for missing templates, SQL, or capture targets by writing prose placeholders that the compiler must guess.

# References

- `references/authoring-dsl.md`
- `assets/examples/users-authoring-plan.yaml`
