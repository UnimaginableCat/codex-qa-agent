# Downstream Modes

## Purpose

These phases come after plan authoring/generation. They are optional and should not be confused
with the primary job of this skill, which is to produce a good `NormalizedTestPlan`.

They are not default behavior for a short generation request. The agent should stop at
`NormalizedTestPlan` unless the user explicitly asked for more.

Treat this reference as the downstream half of the multi-mode `test-plan-generation` skill:

- `evidence`
- `render`
- `promote`
- `validate`

If the user only asked for plan generation, do not use this reference as a reason to continue into
later phases.

## Entry Conditions

Use the minimum downstream phase that matches the request:

- `evidence`: the user wants route grounding, code facts, or coverage alignment.
- `render`: the user wants markdown draft scenarios or previews.
- `promote`: the user wants actual scenario files under `scenarios/generated`.
- `validate`: the user wants parser, compile, or preflight checks on scenario markdown.

If the requested phase depends on missing artifacts, run only the minimum prerequisite phases first.

## Evidence And Enrichment

Use evidence/enrichment only when you need code-derived route or interface facts.

When code facts are collected, generation also computes a coverage assessment:

- authored API cases covered by extracted endpoint facts
- extracted endpoint facts covered by authored API cases
- broad/overlapping matches
- deterministic missing-case suggestions for uncovered endpoint facts

Requirements:

- explicit `project_path`
- explicit evidence scope paths
- optional `stack_hint` only when already known

Example:

```powershell
<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --evidence-scope-path app/api/users.py
```

Do not use evidence collection as implicit repository discovery.

If the operator wants generation to block on uncovered endpoint facts or uncovered authored API
cases, add `--strict-coverage`.

Example:

```powershell
<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --strict-coverage `
  --evidence-scope-path app/api/users.py `
  --output-format text
```

## Draft Rendering

Use draft rendering only when the operator wants markdown preview scenarios after plan generation.

Example:

```powershell
<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --render-drafts `
  --evidence-scope-path app/api/users.py
```

Drafts are previews only. They are not execution-ready by default.

If the user says `drafts`, `preview`, or `markdown scenarios`, stop here unless they also asked for
promotion.

## Review And Promotion

Use this phase when the operator wants actual scenario files rather than previews.

Review:

```powershell
<venv-python> -m tools.generation.cli `
  --review-drafts `
  --run-id <generation-run-id> `
  --workspace-root .
```

Review output may now include `coverage_missing_case_suggestion` diagnostics when a collected
endpoint fact has no authored case. Treat these as authoring follow-ups before promotion.

Promote:

```powershell
<venv-python> -m tools.generation.cli `
  --promote-draft `
  --run-id <generation-run-id> `
  --draft-id draft-tc-001 `
  --workspace-root . `
  --target-dir scenarios/generated

<venv-python> -m tools.generation.cli `
  --promote-all-drafts `
  --run-id <generation-run-id> `
  --workspace-root . `
  --target-dir scenarios/generated
```

Promotion is explicit. Never auto-promote after rendering unless the operator explicitly asked for
scenario files. For requests like "convert all rendered drafts into scenarios", review first and
then use `--promote-all-drafts` so the flow ends with promoted `.md` files rather than previews.

Decision rule:

- one selected draft -> `--promote-draft`
- whole rendered set -> `--promote-all-drafts`

## Validation After Editing

Parser-only:

```powershell
<venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/example.md `
  --output-format text
```

Compile-only:

```powershell
<venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/example.md `
  --mode compile `
  --output-format text
```

Preflight-only:

```powershell
<venv-python> -m tools.generation.cli `
  --validate-scenario `
  --path scenarios/generated/example.md `
  --mode preflight `
  --workspace-root . `
  --output-format text
```

These modes are non-executing.

## Decision Rule

After generation:

- stop at `NormalizedTestPlan` unless the user asked for more
- add evidence only when scoped code facts matter
- inspect `coverage-assessment.json` when evidence was collected
- use missing-case suggestions to repair the authored plan before draft polish when coverage is incomplete
- render drafts only when preview markdown is needed
- review/promote only when the operator wants scenario files
- validate only after manual editing or readiness checks
- keep one run = one canonical bundle under `artifacts/agent/generation/<source>-<run_id>/`
