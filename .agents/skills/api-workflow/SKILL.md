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
- code-analysis findings only if additional clarification is needed

# Execution workflow

1. Read the API step carefully.
2. Resolve:
   - method
   - path
   - headers
   - body
   - dependencies on previous steps
3. Resolve scenario variables from:
   - explicit scenario values
   - prior captured outputs
   - environment values if appropriate
   - generated runtime values if explicitly required by the scenario
   - machine-readable derived/template variables such as `derived:run_suffix|lower` and `template:...`

Do not treat prose variable descriptions as values. A variable definition such as `email_suffix = the lowercase form of run_suffix` is invalid and should block before any HTTP request is sent. Use `email_suffix = derived:run_suffix|lower` instead.
4. Before execution, use `env-resolution` if the environment path, auth configuration, credentials, or base URL are unclear.
5. Load the correct env file.
6. Determine auth strategy from env/config first.
7. Execute the request through `tools/api/run_request.py`.
8. Evaluate the result against expectations.
9. Record the outcome and important evidence.

# Auth policy

Prefer environment-driven authentication as the source of truth.

Auth selection priority:
1. explicit env/config auth strategy
2. scenario-defined auth flow if the scenario explicitly requires a custom flow
3. request headers already fully resolved by the scenario, if they are clearly intentional and not contradictory

If env/config says to use Basic Auth:
- use Basic Auth
- do not switch to JWT or bearer token automatically
- do not invent a token acquisition flow unless the scenario explicitly defines one

If env/config says to use bearer token:
- use bearer token from env/config or an explicit scenario auth flow
- do not silently switch to Basic Auth unless the scenario explicitly requires it

If auth configuration is missing, contradictory, or unresolved:
- mark the step as `BLOCKED`
- explain what is missing or conflicting

# Header and body handling policy

- Preserve scenario-defined headers and body fields unless there is a clear reason not to.
- Do not silently drop request fields.
- If auth is env-driven, prefer not duplicating or overriding auth headers unless the scenario explicitly requires it.
- If both scenario headers and env auth define conflicting authentication methods, prefer env/config auth and record the conflict in the report.

# Validation rules

Check as applicable:
- HTTP status code
- response JSON presence
- specific fields
- field values
- error structure
- consistency with scenario-defined expectations
- consistency with code-analysis findings only if code-analysis was actually used

# Variable capture policy

If the scenario declares captures, extract them from the response and make them available to later steps.

Typical examples:
- `response.json.id -> created_price_list_id`
- `response.json.root_category_id -> created_root_category_id`

If a required capture cannot be extracted because the response shape is different:
- treat this as `FAIL` if the response itself was successful but did not match expectations
- treat this as `ERROR` only if parsing or tooling failed

# Status rules

- PASS — request executed and matched expectations
- FAIL — request executed but expectations were not met
- BLOCKED — missing base URL, missing credentials, missing auth config, unresolved required variables, service unavailable, or auth issue
- ERROR — tool/runtime/parsing failure

# Code analysis policy

Code-analysis is optional, not required for normal API execution.

Use code-analysis only when:
- the scenario does not clearly define expected behavior
- the correct endpoint, request field, or response shape is uncertain
- the runtime result contradicts scenario expectations
- debugging requires implementation evidence

Do not inspect the codebase by default when the scenario already provides:
- explicit HTTP method
- explicit path
- explicit headers/body
- explicit expected response shape
- clear success criteria

# Artifact handling

Save or reference:
- request definition used
- resolved auth mode used, without exposing secrets
- raw response
- parsed JSON if available
- validation summary
- captured variables if relevant
- tooling issues or auth conflicts if any

# Guardrails

- Never print secrets or full credentials.
- Never expose Authorization header values, passwords, or tokens in the report.
- Do not silently drop headers or body fields.
- Do not mark missing env/auth as FAIL.
- Do not fake successful results if the service is unreachable.
- Do not invent auth flows, endpoints, or response fields without saying so explicitly.
- If auth mode came from env/config, say so briefly in the report.
- If scenario and env/config auth definitions conflicted, say so clearly in the report.

# Completion criteria

This skill is complete when the API step has:
- been executed or clearly marked BLOCKED/ERROR
- been validated against expectations
- produced evidence usable in the final report
- recorded relevant captures, assumptions, and tooling/auth issues
