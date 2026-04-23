# Generation Pipeline Foundation

Phase 1 generation artifacts are isolated from `scenario_runner` artifacts while keeping a familiar
run-state plus immutable-bundle shape.

Run state:

```text
.codex-qa/generation/runs/<run_id>/
  context.json
  evidence.json        # only when code facts collection is enabled
  summary.json
```

Artifact bundle:

```text
artifacts/agent/generation/<source_slug>-<run_id>/
  manifest.json
  context.json
  source-input.json
  normalized-source.json
  normalized-plan.json
  traceability-map.json
  diagnostics.json
  evidence-bundle.json # only when code facts collection is enabled
  enriched-plan.json   # only when evidence enrichment is enabled
  enrichment-result.json
  applied-evidence.json
  unapplied-evidence.json
  scenario-drafts/
    <draft>.md
  scenario-render-result.json
  scenario-parse-results.json
  unsupported-checks.json
  deferred-items.json
  promotion-result.json
  summary.json
```

Canonical Phase 1 contracts live in `tools.generation.domain.models`.
The canonical application entrypoint is `GenerateTestPlanUseCase` with `GenerateTestPlanRequest`.
It builds a prose-first `NormalizedTestPlan` and intentionally stops before scenario synthesis,
pause/resume, plan enrichment, and LLM/API integration.

Code facts are a separate opt-in evidence layer. Canonical evidence contracts live in
`tools.generation.evidence.models`; the extractor interface is `CodeFactsExtractor`.
`ApiSurfaceFactsExtractor` currently supports targeted Python API-surface extraction only from
explicit scoped paths and returns a `GenerationEvidenceBundle`. Evidence is returned beside the
generation result and persisted as evidence artifacts.

Evidence enrichment is a separate opt-in phase. Canonical enrichment contracts live in
`tools.generation.enrichment.models`; the service boundary is `TestPlanEnricher`, with
`EvidenceToPlanEnricher` as the deterministic implementation. Enrichment may attach endpoint
hints, readiness metadata, diagnostics, and traceability links to relevant `PlannedTestCase`
records. It does not render runnable scenarios and does not replace prose-first planning.

Agent-facing adapter:

```powershell
py -3.14 -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user" `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --evidence-scope-path app/api/users.py
```

The adapter only gathers arguments, builds typed request objects, calls `GenerateTestPlanUseCase`,
and prints a JSON summary. It does not scan outside explicit evidence scope paths.

Draft scenario rendering preview:

```powershell
py -3.14 -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user" `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --render-drafts `
  --evidence-scope-path app/api/users.py
```

Rendering is conservative: it emits parser-validated markdown previews only for cases with endpoint
path and HTTP method evidence hints. Unsupported cases are written to deferred/unsupported artifacts.
No scenario execution, compile, preflight, API workflow, or DB workflow is triggered.

Review and promotion:

```powershell
py -3.14 -m tools.generation.cli `
  --review-drafts `
  --run-id <generation-run-id> `
  --workspace-root .

py -3.14 -m tools.generation.cli `
  --promote-draft `
  --run-id <generation-run-id> `
  --draft-id draft-tc-001 `
  --workspace-root . `
  --target-dir scenarios/generated
```

Promotion is explicit, never overwrites existing files, and writes `promotion-result.json` under the
generation artifact bundle. Promoted drafts receive a metadata header and are not executed.
