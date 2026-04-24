# Generation Pipeline Foundation

Phase 1 generation artifacts are isolated from `scenario_runner` artifacts.

Canonical request bundle:

```text
artifacts/agent/generation/<source_slug>-<run_id>/
  manifest.json
  agent-plan.json
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

Treat this bundle as the single source of truth for one generation request. Do not split one
request across a separate run-state tree and a second artifact tree.

Canonical Phase 1 contracts live in `tools.generation.domain.models`.
The canonical application entrypoint is `GenerateTestPlanUseCase` with `GenerateTestPlanRequest`.
It builds a canonical `NormalizedTestPlan` and intentionally stops before runner execution,
pause/resume, and LLM/API integration.

Primary input path:

```text
agent-authored plan input -> GenerateTestPlanUseCase -> NormalizedTestPlan
```

The typed primary input contracts are `AgentTestPlanInput` and `AgentPlannedTestCaseInput`.
This path should be used when the agent can decompose a broad operator request into explicit
planned cases. The older prose path remains as a fallback/bootstrap mode:

```text
prose -> prose normalizer -> NormalizedTestPlan
```

Both paths use the same downstream evidence, enrichment, rendering, review, promotion, and
validation services.

Authoring helper workflow:

```text
agent reasoning
-> scaffold AgentTestPlanInput
-> validate AgentTestPlanInput
-> run generation
```

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

CLI validate-only:

```powershell
<project-venv-python> -m tools.generation.cli `
  --validate-agent-plan `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
  --output-format text
```

The scaffolded template is deterministic and section-complete for Phase 1 authoring. Validation is
deterministic and checks required top-level fields, case presence, required case fields, malformed
JSON, and unsupported payload shape before full generation runs.

`--init-agent-plan` now creates a fresh canonical request bundle under
`artifacts/agent/generation/<source>-<run_id>/` and writes the scaffold directly to
`agent-plan.json` inside that bundle. Treat the returned bundle path as the primary result of the
request, not the raw `--output` hint.

After generation, the authored input is persisted inside the canonical request bundle as
`agent-plan.json`. Treat that bundle copy as the canonical request artifact.

Code facts are a separate opt-in evidence layer. Canonical evidence contracts live in
`tools.generation.evidence.models`; the extractor interface is `CodeFactsExtractor`, and the
stack-aware orchestration boundary is `CodeFactsExtractionService`. Extractor selection is
deterministic:

- explicit `CodeFactsScope.stack_hint`, when compatible with the explicit scope paths
- otherwise explicit scope file characteristics
  - `.py` -> `PythonApiSurfaceFactsExtractor`
  - `.java` with Spring controller/mapping annotations -> `JavaSpringApiSurfaceFactsExtractor`

If the scope is mixed, unsupported, or not applicable to a supported extractor, the service returns
diagnostics in the unified `GenerationEvidenceBundle` instead of silently applying the wrong parser.
Evidence is returned beside the generation result and persisted as evidence artifacts.

Evidence enrichment is a separate opt-in phase. Canonical enrichment contracts live in
`tools.generation.enrichment.models`; the service boundary is `TestPlanEnricher`, with
`EvidenceToPlanEnricher` as the deterministic implementation. Enrichment may attach endpoint
hints, readiness metadata, diagnostics, and traceability links to relevant `PlannedTestCase`
records. It does not render runnable scenarios and does not replace prose-first planning.

Agent-facing adapter:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --evidence-scope-path app/api/users.py
```

Java/Spring controller scope uses the same flow, optionally with an explicit stack hint:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
  --workspace-root . `
  --project-path code/demo `
  --collect-code-facts `
  --enrich `
  --stack-hint java_spring `
  --evidence-scope-path src/main/java/demo/UserController.java
```

The adapter only gathers arguments, builds typed request objects, calls `GenerateTestPlanUseCase`,
and prints a JSON summary. It does not scan outside explicit evidence scope paths or perform
repository-wide stack discovery.

Fallback prose adapter:

```powershell
<project-venv-python> -m tools.generation.cli `
  --source-id users-api `
  --project code/demo `
  --prose "Verify create user" `
  --workspace-root .
```

When invoking generation locally, prefer the target project's resolved venv/interpreter first.
Use `py -3.14` only as fallback when no project-specific interpreter is available.

Draft scenario rendering preview:

```powershell
<project-venv-python> -m tools.generation.cli `
  --agent-plan-file artifacts/agent/generation/users-api-<run_id>/agent-plan.json `
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
```

Promotion is explicit, never overwrites existing files, and writes `promotion-result.json` under the
generation artifact bundle. When using the default `scenarios/generated` root, promoted drafts are
written under a run-scoped subdirectory such as `scenarios/generated/<source>-<run_id>/` so
separate generation runs do not collide. Promoted drafts receive a metadata header and are not
executed.
