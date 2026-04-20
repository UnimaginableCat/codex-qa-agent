---
name: api-workflow
description: Use this skill to execute scenario API steps against a target environment, validate responses, and save request/response evidence for the final QA report.
---

# Purpose

This skill handles HTTP-based scenario steps.

Use this skill when:
- a scenario step is of type API
- authentication may be needed
- request/response evidence should be captured
- response expectations should be validated

# Inputs to read

- the current scenario step
- the scenario environment path
- `env/<project>.env`
- prior step outputs if the current step depends on them
- code-analysis findings for expected behavior

# Execution workflow

1. Read the API step carefully.
2. Resolve:
   - method
   - path
   - headers
   - body
   - dependencies on previous steps
3. Before execution, use `env-resolution` if the environment path, auth token, credentials, or base URL are unclear.
4. Load the correct env file.
5. Determine auth strategy:
   - use bearer token if already present
   - otherwise respect scenario-provided auth flow if defined
6. Execute the request through `tools/api/run_request.py`.
7. Evaluate the result against expectations.
8. Record the outcome and important evidence.

# Validation rules

Check as applicable:
- HTTP status code
- response JSON presence
- specific fields
- field values
- error structure
- consistency with analyzed code path

# Status rules

- PASS — request executed and matched expectations
- FAIL — request executed but expectations were not met
- BLOCKED — missing URL, token, credentials, service unavailable, auth issue
- ERROR — tool/runtime/parsing failure

# Artifact handling

Save or reference:
- request definition used
- raw response
- parsed JSON if available
- validation summary

# Guardrails

- Never print secrets or full credentials.
- Do not silently drop headers or body fields.
- Do not mark missing env/auth as FAIL.
- Do not fake successful results if the service is unreachable.

# Completion criteria

This skill is complete when the API step has:
- been executed or clearly marked BLOCKED/ERROR
- been validated against expectations
- produced evidence usable in the final report