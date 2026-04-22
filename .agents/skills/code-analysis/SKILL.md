---
name: code-analysis
description: Use this skill to inspect a target project under code/ only when a QA scenario is ambiguous, runtime results need clarification, or implementation evidence is needed for debugging or reporting.
---

# Purpose

This skill provides implementation-backed clarification for QA execution when the scenario alone is not sufficient.

Use this skill when:
- a scenario references an endpoint or business flow, but the expected behavior is unclear
- you need to verify which code path is actually responsible for a response or side effect
- API or DB results contradict scenario expectations
- you need to identify likely DB side effects that are not explicit in the scenario
- you need targeted debugging evidence for a FAIL / ERROR / unexpected runtime result

For runnable scenarios, do not use this skill before the first `scenario_runner` execution by default. Runner execution comes first, then artifact reading, then targeted code analysis only if the runner result or the user asks for it.

Do not use this skill by default if the scenario already provides:
- explicit API paths
- required request fields
- expected response fields
- expected DB queries or tables
- clear success criteria

# Inputs to inspect

Inspect only what is needed for the current ambiguity or failure:
- the scenario file
- the target project under `code/<project-name>`
- routes/controllers/views if endpoint resolution is needed
- services/use-cases if business logic is unclear
- repositories/DAOs/models/entities if DB side effects must be clarified
- serializers/DTOs/schemas if response/request shape is uncertain
- existing tests if they can confirm intended behavior
- config files only if relevant to the issue being investigated

Avoid broad codebase scanning unless absolutely necessary.

# Analysis workflow

1. Identify the target project.
2. Confirm why code inspection is needed: explicit user request, scenario ambiguity that blocks runner startup, or runner artifacts showing `FAIL`, `BLOCKED`, `ERROR`, contradiction, or incomplete evidence.
3. Narrow analysis to the smallest relevant implementation area, for example:
   - HTTP route
   - controller/view
   - command handler
   - service method
   - serializer/schema
   - repository/model
4. Trace only the relevant code path.
5. Extract only the evidence needed to guide execution or explain the result:
   - validations
   - auth requirements
   - side effects
   - DB writes/reads
   - expected response shape
   - likely failure points
6. If useful, check related tests for confirmation.
7. Summarize findings concisely.

# What to extract

Try to answer only the questions relevant to the current need:
- which endpoint or handler is involved
- which request fields are required
- which service/use-case executes the business logic
- which tables/entities are likely affected
- what response is expected
- what preconditions are required
- what failure modes are likely
- why an observed runtime result may differ from scenario expectations

Do not extract unrelated implementation details.

# Output format

Produce a concise structured summary with:
- target project
- scenario step or feature being analyzed
- reason code analysis was needed
- probable code path
- expected DB side effects
- expected response shape
- likely risks/blockers
- confidence level if uncertain

# Guardrails

- Prefer direct code evidence over guesses.
- If multiple paths are possible, say so explicitly.
- If you cannot find an implementation detail, mark it as uncertain.
- Do not claim behavior that is not supported by code or tests.
- Do not scan large parts of the codebase when a narrow targeted lookup is enough.
- If the scenario is already explicit enough, skip code analysis.
- If a runnable scenario has not been executed yet, do not do pre-run broad code scanning unless the user explicitly requested it or runner startup is blocked by a narrow ambiguity.
- Do not edit runner-generated artifacts while doing code analysis.

# Completion criteria

This skill is complete when the specific ambiguity, contradiction, or debugging need has been clarified well enough to guide API/DB execution or improve the final report.
