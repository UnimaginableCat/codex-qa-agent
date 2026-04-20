---
name: code-analysis
description: Use this skill to map a QA scenario to real implementation paths in a target project under code/, including routes, controllers, services, repositories, entities, serializers, DTOs, tests, and likely side effects.
---

# Purpose

This skill analyzes the code before execution so later checks are grounded in the actual implementation.

Use this skill when:
- a scenario references an endpoint or business flow
- you need to understand what the system is supposed to do
- you need to identify where DB side effects should appear
- you need to find likely failure points before runtime checks

# Inputs to inspect

- the scenario file
- the target project under `code/<project-name>`
- routes/controllers/views
- services/use-cases
- repositories/DAOs/models/entities
- serializers/DTOs/schemas
- existing tests
- config files if relevant

# Analysis workflow

1. Identify the target project.
2. Identify the entry point:
   - HTTP route
   - controller/view
   - command handler
   - service method
3. Trace the main code path.
4. Identify:
   - validations
   - auth requirements
   - side effects
   - DB writes/reads
   - expected response shape
5. Find related tests and compare intended behavior.
6. Summarize likely execution behavior.

# What to extract

Try to answer:
- which endpoint or handler is involved
- which request fields are required
- which service/use-case executes the business logic
- which tables/entities are likely affected
- what response is expected
- what preconditions are required
- what failure modes are likely

# Output format

Produce a concise structured summary with:
- target project
- scenario step or feature being analyzed
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

# Completion criteria

This skill is complete when the later API/DB execution can be guided by concrete implementation evidence rather than vague assumptions.