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

Apply the `AGENTS.md` workspace interpreter rule before any CLI command. Resolve `<venv-python>` with the public generation CLI probe (`-m tools.generation.cli --help`) and reuse that exact interpreter for all commands in the turn.

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
- Never write an update such as "entity inventory passed" or "operation inventory passed" after a command display that shows `(no output)`. That is an unknown gate result, not `PASS`.
- downstream compile/render/promote work is left to `test-plan-generation`
- final responses for this skill must explicitly say that the result is an authoring bundle only:
  no runnable scenario drafts were rendered, no scenarios were promoted, and downstream generation
  requires `test-plan-generation` or an explicit compile/render command

# Invocation

The normal user-facing entry point is `qa-entrypoint`.

Call this skill directly only when the routing decision is already explicit and the request should
start inside the authoring branch rather than being classified first.

# Authoring Rules

Keep `SKILL.md` focused on the authoring workflow. Load `references/authoring-guardrails.md` only when a broad runnable bundle, validation diagnostic, permissions/role case, lifecycle case, or assertion-shape repair needs detailed guidance.

Core rules:

- Author compact YAML DSL, not full `AgentTestPlanInput` and not prose Markdown docs.
- Use staged files in order: `entity-inventory.yaml`, `operation-inventory.yaml`, synced `authoring-plan.yaml`, then bundle validation.
- Keep cases deterministic: supported expectation DSL, explicit captures, explicit setup, and persisted-state checks for mutating cases.
- Prove route paths, HTTP methods, request bodies, auth profiles, variables, and DB checks with structured evidence rather than prose.
- Prove every mutating/action-like route `success_status` with structured `success_status_evidence`; do not infer `201` from POST/create/duplicate naming or from method evidence.
- Prove risky business semantics with structured `behavior_evidence` from the same executed flow; do not use update service/test evidence to justify create-flow expectations.
- Keep entity identity real. Do not change an entity `id_field` to a convenient captured variable just to satisfy persisted-state validation.
- Keep reusable DB verifications invariant or parameterized. Formula-link checks must match the non-system variables used by that case's `quantity_formula`; never hardcode one expected variable into a generic formula-link verifier.
- Preserve coverage intent when validation fails. Add missing evidence/setup/captures or defer/report the blocker; do not weaken or delete assertions just to pass a gate.
- Generated scenarios must be self-contained; do not rely on another scenario having run first.

Read `references/authoring-dsl.md` for field shapes and `references/authoring-guardrails.md` for detailed repair rules.

## Staged Authoring

For broad coverage, use the managed staged bundle flow one gate at a time:

1. `entity-inventory.yaml` -> `--validate-entity-inventory`
2. `operation-inventory.yaml` -> `--validate-operation-inventory`
3. `--sync-authoring-plan`
4. authored cases in `authoring-plan.yaml` -> `--validate-authoring-plan`
5. `--validate-authoring-bundle`

Do not edit all staged files in one pass. If a later stage exposes an inventory defect, return to that inventory, validate it, sync again, and revalidate the bundle.
After changing operation inventory, rerun sync. Do not manually mirror the changed setup operation or DB template into synced `authoring-plan.yaml` sections.

Read `references/staged-authoring.md` for inventory contents, sync semantics, and repair loops.

## Bundle Validation And DSL Gate

Before downstream generation, run the bundle-level gate:

`<venv-python> -m tools.generation.cli --validate-authoring-bundle --path artifacts/agent/generation/<run_id> --output-format text`

This gate must show explicit `Status: PASS` or JSON `status=PASS` before the bundle is reported ready. If it reports expectation syntax, setup state, identity, permission, request-body, route, lifecycle, or DB-scope diagnostics, repair the staged source and rerun the gate.

For assertion syntax, use only supported deterministic DSL. Unsupported prose-like checks must be rewritten as supported JSON path assertions, DB verification, or deferred blockers; never weaken the behavioral oracle to `response body exists` unless body existence is the behavior under test.

Read `references/authoring-guardrails.md` for the detailed diagnostic repair policy.

# CLI Flow

Use the exact generation module entrypoint `-m tools.generation.cli`. Do not probe or document
`-m tools.generation`; the package itself is not the CLI contract.

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
- Do not use broad regex rewrites such as `perl -pi`, `sed -i`, or whole-file replacements on authoring bundles to make validation pass. Use targeted edits and preserve the stronger request, assertion, capture, and DB verification contracts unless code/schema evidence proves they were wrong.

# References

- `references/authoring-dsl.md`
- `references/authoring-guardrails.md`
- `references/staged-authoring.md`
- `assets/examples/users-authoring-plan.yaml`
