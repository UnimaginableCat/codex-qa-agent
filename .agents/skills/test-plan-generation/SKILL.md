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
- Coverage assessment: when code facts are collected, authored API cases are compared against extracted endpoint facts.
- Enrichment: optional evidence-to-plan updates; do not treat them as runnable scenarios.
- Rendering/review/validation: downstream phases after plan generation.
- CLI: thin adapter over service contracts. Do not invent generation semantics in the agent.

# Core Commands

Use the target project/workspace venv interpreter first. If no suitable venv exists, use `py -3.14`
only as fallback.

- Scaffold structured plan: `<venv-python> -m tools.generation.cli --init-agent-plan --output artifacts/agent/generation --source-id <id> --project code/<project> --name "<title>" --goal "<goal>"`
- Validate structured plan: `<venv-python> -m tools.generation.cli --validate-agent-plan --agent-plan-file <bundle>/agent-plan.json --output-format text`
- Generate from structured plan: `<venv-python> -m tools.generation.cli --agent-plan-file <bundle>/agent-plan.json --workspace-root .`
- Generate with evidence/enrichment: `<venv-python> -m tools.generation.cli --agent-plan-file <bundle>/agent-plan.json --workspace-root . --project-path code/<project> --collect-code-facts --enrich --evidence-scope-path <path>`
- Generate with strict coverage guardrail: `<venv-python> -m tools.generation.cli --agent-plan-file <bundle>/agent-plan.json --workspace-root . --project-path code/<project> --collect-code-facts --strict-coverage --evidence-scope-path <path> --output-format text`

Use prose only when the user explicitly wants bootstrap from prose or the agent cannot yet author a
useful structured plan:

- Prose fallback: `<venv-python> -m tools.generation.cli --source-id <id> --project code/<project> --prose "<text>" --workspace-root .`

# Default Decisions

- Use `agent_plan` unless the request is too vague or the user explicitly wants prose bootstrap.
- Decompose first for controller, feature, lifecycle, workflow, validation, or API-surface requests.
- Validate structured input before generation when the agent authored or edited JSON.
- Use evidence when the user asked for it, when route/fact grounding is needed, or when coverage alignment must be checked against real endpoint facts.
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
- When the request is about a full workflow or full controller functionality, prefer at least one true end-to-end case with `workflow_steps[]` instead of only single-endpoint cases.
- When that workflow includes successful state-changing API steps, treat persisted-state verification as part of the default contract: author either case-level `db_verification` or at least one `workflow_steps[]` entry with `step_type=db`.
- For `kind=api` and `kind=db`, treat `expected_outcomes[]` as runner-compatible expectation DSL, not free-form prose.
- Put high-level behavior into `observable_outcomes[]` and use `expected_outcomes[]` only for executable assertions the downstream scenario renderer can preserve.

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
- `scenario-aligned`: API/DB expectations and captures are already compatible with downstream scenario syntax
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
8. Add explicit evidence scope when the next requested phase needs code facts or authored coverage must be checked against extracted endpoint facts.
9. If code facts were collected, inspect `coverage_assessment` before draft rendering and treat uncovered endpoint facts as plan gaps, not as a drafting problem.
10. Continue to enrichment/rendering/review only if the user asked for those phases.

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

One generation request should resolve to one canonical bundle:

```text
artifacts/agent/generation/<source_slug>-<run_id>/
```

Treat this bundle as the single source of truth for that request. It contains the persisted
`agent-plan.json`, `context.json`, `normalized-plan.json`, diagnostics, optional evidence, and any
downstream draft/review artifacts for the same run.

For a new request, do not start from an old plan file in an arbitrary folder. Create a fresh
bundle with `--init-agent-plan`, work on that bundle's `agent-plan.json`, and only reuse an older
bundle when the user explicitly asks to continue that exact request.

Treat `normalized-plan.json` as the canonical generated plan artifact. Do not treat draft markdown,
review output, or validation output as the canonical plan.

When evidence is collected, also expect `coverage-assessment.json`. Treat it as the canonical
authored-plan-vs-endpoint-facts coverage view for that run.

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
- Do not use free-form narrative `expected_outcomes[]` for API/DB cases when downstream scenario syntax is already known.
- Do not ignore uncovered endpoint facts after collecting evidence; either tighten the scope, add the missing case, or use `--strict-coverage` when the user wants blocking behavior.
- Do not call LLMs or external APIs from local generation services.
- Do not treat generated draft markdown as executable or reviewed scenarios.
- Do not auto-promote after a generation-only request or overwrite existing scenario files.
- When the user explicitly asks for scenario files for the whole rendered set, continue through review
  and use `--promote-all-drafts` instead of stopping at draft previews.
- Do not store canonical planning fields only in `metadata`.
