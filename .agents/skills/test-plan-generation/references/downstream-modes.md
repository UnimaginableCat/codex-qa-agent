# Downstream Modes

## Purpose

These phases come after plan authoring/generation. They are optional and should not be confused
with the primary job of this skill, which is to produce a good `NormalizedTestPlan`.

## Evidence And Enrichment

Use evidence/enrichment only when you need code-derived route or interface facts.

Requirements:

- explicit `project_path`
- explicit evidence scope paths
- optional `stack_hint` only when already known

Example:

```powershell
<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/input/users-api-plan.json `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --evidence-scope-path app/api/users.py
```

Do not use evidence collection as implicit repository discovery.

## Draft Rendering

Use draft rendering only when the operator wants markdown preview scenarios after plan generation.

Example:

```powershell
<venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/input/users-api-plan.json `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --render-drafts `
  --evidence-scope-path app/api/users.py
```

Drafts are previews only. They are not execution-ready by default.

## Review And Promotion

Review:

```powershell
<venv-python> -m tools.generation.cli `
  --review-drafts `
  --run-id <generation-run-id> `
  --workspace-root .
```

Promote:

```powershell
<venv-python> -m tools.generation.cli `
  --promote-draft `
  --run-id <generation-run-id> `
  --draft-id draft-tc-001 `
  --workspace-root . `
  --target-dir scenarios/generated
```

Promotion is explicit. Never auto-promote.

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
- render drafts only when preview markdown is needed
- review/promote only when the operator wants scenario files
- validate only after manual editing or readiness checks
