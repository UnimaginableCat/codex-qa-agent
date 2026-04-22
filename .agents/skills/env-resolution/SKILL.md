---
name: env-resolution
description: Use this skill to resolve which environment file, credentials, tokens, base URLs, and DB connection settings should be used for a scenario, and to classify missing configuration correctly.
---

# Purpose

This skill standardizes how environment configuration is resolved before API or DB execution.

Use this skill when:
- a scenario references an environment file
- a project has multiple env files
- API base URL, auth token, credentials, or DB connection settings are required
- it is unclear whether a failure is due to product behavior or missing configuration

# Inputs to inspect

- the scenario file
- environment path in the scenario
- files under `env/`
- relevant notes from `AGENTS.md`
- any user-provided credentials or tokens
- prior execution context if a previous step produced a token or identifier

# Resolution workflow

1. Read the scenario and locate the declared environment file.
2. For runnable scenarios, prefer the runner preflight as the first readiness check unless the user explicitly asked for manual env analysis or the runner cannot start without env path clarification.
3. Determine whether the env file exists.
4. Identify required configuration for the current step.
5. Resolve values from the env file or prior step outputs.
6. Identify missing required values.
7. Classify the outcome:
   - ready to execute
   - blocked by missing config
   - blocked by missing credentials
   - blocked by missing DB access
8. Provide a short normalized configuration summary without exposing secrets.

# Common configuration fields

Check for fields like:
- API_BASE_URL
- API_BEARER_TOKEN
- API_USERNAME
- API_PASSWORD
- DATABASE_URL
- optional project-specific variables

# Output requirements

Produce a concise env-resolution summary containing:
- target env file
- whether it exists
- which required fields were found
- which required fields are missing
- whether execution can proceed
- sanitized notes about auth strategy

Do not print actual secret values.

# Classification rules

Use BLOCKED when:
- the declared env file does not exist
- required URL/token/credentials are missing
- DB connection string is missing
- environment is clearly not runnable

Do not classify these as FAIL.

Use ready-to-execute when:
- required values are present
- auth/config dependencies are satisfied or can be derived from earlier steps

# Interaction with other skills

- `api-workflow` should use this skill before sending requests if env is unclear.
- `db-verification` should use this skill before opening DB connections.
- `runner-execution` relies on the runner preflight for scenario readiness; use this skill for manual clarification when env/config blockers need explanation.
- Do not turn guided/manual execution into pre-run env investigation unless runner startup is blocked or the user requested env analysis.

# Guardrails

- Never expose tokens, passwords, or raw secrets.
- Never pretend missing config is a product failure.
- Never silently ignore missing required variables.
- If multiple env files are plausible, say which one was selected and why.
- Do not edit runner-generated artifacts while resolving environment issues.

# Completion criteria

This skill is complete when:
- the correct env file was identified or clearly missing
- required configuration was checked
- missing values were classified correctly
- execution readiness is clear
