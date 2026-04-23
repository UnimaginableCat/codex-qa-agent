---
name: test-plan-generation
description: Generate a typed NormalizedTestPlan in the local codex-qa-agent workspace. Prefer agent-authored structured plan input when the agent can decompose the request; use prose input only as fallback/bootstrap. Use when the desired output is PlannedTestCase items plus diagnostics/artifacts rather than scenario_runner execution.
---

# Purpose

Use this skill as the default path for test-plan generation in this workspace.

Prefer the structured `agent_plan` path over prose normalization when the agent can decompose a
feature, controller, or API request into explicit planned cases. Prose mode exists only as
fallback/bootstrap when no meaningful decomposition is available yet.

The canonical output remains `NormalizedTestPlan`. Optional downstream stages such as evidence
collection, enrichment, draft rendering, review, and validation stay separate from the initial
authoring step.

# Default Interpretation

Assume the user will usually provide only:

- target project
- feature/controller/API request
- optional explicit scope

That is enough for this skill in the normal case.

Given a short request such as:

```text
project: code/<project-name>
request: <feature/controller/API scope>
```

the agent should, by default:

1. choose `agent_plan` as the primary path
2. decompose the request into `AgentTestPlanInput`
3. scaffold/fill structured input as needed
4. validate the structured plan
5. run generation from `--agent-plan-file`

Do not expect the user to restate these decisions in the prompt.

# Architecture Boundaries

- Authoring: `AgentTestPlanInput` and `AgentPlannedTestCaseInput`.
- Generation: `GenerateTestPlanUseCase` produces `NormalizedTestPlan`.
- Evidence: explicit scoped code facts only; never broad repository discovery.
- Enrichment: optional evidence-to-plan updates; do not treat them as runnable scenarios.
- Rendering/review/validation: downstream phases after plan generation.
- CLI: thin adapter over service contracts. Do not invent generation semantics in the agent.

# Core Commands

Use the target project/workspace venv interpreter first. If no suitable venv exists, use `py -3.14`
only as fallback.

- Scaffold structured plan: `<venv-python> -m tools.generation.cli --init-agent-plan --output <plan.json> --source-id <id> --project code/<project> --name "<title>" --goal "<goal>"`
- Validate structured plan: `<venv-python> -m tools.generation.cli --validate-agent-plan --agent-plan-file <plan.json> --output-format text`
- Generate from structured plan: `<venv-python> -m tools.generation.cli --agent-plan-file <plan.json> --workspace-root .`
- Generate with evidence/enrichment: `<venv-python> -m tools.generation.cli --agent-plan-file <plan.json> --workspace-root . --project-path code/<project> --collect-code-facts --enrich --evidence-scope-path <path>`

Use prose only when the user explicitly wants bootstrap from prose or the agent cannot yet author a
useful structured plan:

- Prose fallback: `<venv-python> -m tools.generation.cli --source-id <id> --project code/<project> --prose "<text>" --workspace-root .`

# Default Decisions

- Use `agent_plan` unless the request is too vague or the user explicitly wants prose bootstrap.
- Decompose first for controller, feature, lifecycle, workflow, validation, or API-surface requests.
- Validate structured input before generation when the agent authored or edited JSON.
- Use evidence only when the user asked for it or the next requested phase clearly depends on scoped code facts.
- Ask for explicit evidence scope only when evidence/enrichment is actually needed.
- Stop at `NormalizedTestPlan` unless the user asked for downstream phases.

# Decomposition Defaults

For controller/API requests, default to a compact initial plan instead of an exhaustive branch
inventory.

- Start from operations, not internal handlers.
- Use an operation x coverage-bucket matrix.
- Prefer core buckets first: happy path, validation, not found/ownership, and only the state-specific negative cases that matter externally.
- Keep the first plan compact. A good default is roughly `8-10` strong cases unless the user explicitly asked for exhaustive coverage.
- If multiple internal branches lead to the same observable API behavior, merge them into one case instead of splitting them.
- Keep `expected_outcomes` at the observable contract level. Do not fill the initial plan with implementation-only details that do not improve testability or rendering.

For requests like "cover full XController functionality", the agent should default to:

1. identify operations
2. choose core buckets per operation
3. build a compact plan
4. check quality gate
5. only then run generation

# When To Ask The User

Ask only when a real blocker exists, such as:

- target project is unclear
- scope is too ambiguous to decompose responsibly
- user asked for evidence/enrichment but did not provide explicit scope
- multiple plausible project/controller targets exist

Do not ask the user to repeat operational defaults that belong in this skill.

# Plan Quality Gate

Before generation, the agent should quickly check that the plan is:

- `compact`: not inflated by low-value edge splitting
- `observable`: focused on externally visible behavior
- `non-duplicative`: near-duplicate cases merged
- `render-friendly`: cases still map cleanly toward endpoint/method-oriented drafts
- `explicit-unknowns`: unresolved details kept in assumptions/open questions/unresolved items instead of disguised as facts

If the plan fails this gate, reduce or reshape the decomposition before calling generation.

# Primary Workflow

1. Identify the target project and requested feature/controller scope.
2. Decide whether the request is decomposable enough for `agent_plan`. Default to yes for controller/feature/API requests.
3. Decompose into a structured `AgentTestPlanInput`.
4. Scaffold a starter JSON when needed.
5. Fill planned test cases, assumptions, and open questions.
6. Validate the structured plan before generation.
7. Run generation from `--agent-plan-file`.
8. Add explicit evidence scope only when the next requested phase needs code facts.
9. Continue to enrichment/rendering/review only if the user asked for those phases.

# Decomposition Rule

Decompose first, generate second.

For controller/feature requests, the agent should identify the concrete operations, coverage
buckets, and unresolved areas before calling generation. A good structured plan names the real
cases the operator likely expects. It should not rely on the prose normalizer to discover them from
broad intent alone.

Use prose mode only when:

- the request is too small or too vague to justify decomposition yet
- the operator explicitly wants a bootstrap plan from prose
- structured authoring would add unnecessary overhead for the task

# Artifact Expectations

Generation artifacts remain isolated from runner artifacts:

```text
.codex-qa/generation/runs/<run_id>/
artifacts/agent/generation/<source_slug>-<run_id>/
```

Treat `normalized-plan.json` as the canonical generated plan artifact. Do not treat draft markdown,
review output, or validation output as the canonical plan.

# When More Detail Is Needed

Read these references only when needed:

- `references/input-modes.md`: primary `agent_plan` path, prose fallback, and mode selection.
- `references/agent-plan-authoring.md`: scaffold/validate workflow and canonical template shape.
- `references/decomposition-workflow.md`: deterministic decomposition method, patterns, and worked example.
- `references/downstream-modes.md`: evidence, enrichment, draft rendering, review, promotion, and validation.

# Guardrails

- Do not run or modify `scenario_runner` from this skill.
- Do not force broad requests through prose scanning when the agent can author a structured plan.
- Do not skip `--validate-agent-plan` after manually editing structured input.
- Do not collect code facts without explicit scoped paths.
- Do not infer `project_path`, `CodeFactsScope`, or `stack_hint` from vague prose alone.
- Do not perform repository-wide discovery.
- Do not call LLMs or external APIs from local generation services.
- Do not treat generated draft markdown as executable or reviewed scenarios.
- Do not auto-promote drafts or overwrite existing scenario files.
- Do not store canonical planning fields only in `metadata`.
