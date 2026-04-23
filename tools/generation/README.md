# Generation Pipeline Foundation

Phase 1 generation artifacts are isolated from `scenario_runner` artifacts while keeping a familiar
run-state plus immutable-bundle shape.

Run state:

```text
.codex-qa/generation/runs/<run_id>/
  context.json
  summary.json
```

Artifact bundle:

```text
artifacts/agent/generation/<source_slug>-<run_id>/
  manifest.json
  context.json
  source-input.json
  normalized-plan.json
  traceability-map.json
  diagnostics.json
  summary.json
```

Canonical Phase 1 contracts live in `tools.generation.domain.models`.
The orchestration service intentionally stops before scenario synthesis, pause/resume, and LLM/API integration.

