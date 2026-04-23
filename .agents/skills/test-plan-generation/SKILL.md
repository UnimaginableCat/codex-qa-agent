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

# Primary Workflow

1. Identify the target project and the requested feature/controller scope.
2. Decompose the request into a structured `AgentTestPlanInput`.
3. Scaffold a starter JSON when needed.
4. Fill planned test cases, assumptions, and open questions.
5. Validate the structured plan before generation.
6. Run generation from `--agent-plan-file`.
7. Add explicit evidence scope only when the next phase needs code facts.
8. Continue to enrichment/rendering/review only if the user asked for those phases.

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
