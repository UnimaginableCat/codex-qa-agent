# Scenario: <scenario-name>

## Project
code/<project-name>

## Environment
env/<project-name>.env

## Goal
Describe what business functionality should be verified.

## Preconditions
- API is running
- DB is reachable
- required test data exists
- auth/config is available if needed

## Notes
Optional free-form notes for the agent.
Use this section for assumptions, special setup details, or known limitations.

## Variables
- company_guid = env:COMPANY_GUID
- run_suffix = generated:run_suffix
- email_suffix = derived:run_suffix|lower
- generated_name = template:AUTOTEST {{run_suffix}}
- static_label = literal:Fixed literal

## Steps

### Step 1
Type: api
Name: <short-step-name>
Method: POST
Path: /api/example
Headers:
{
  "Content-Type": "application/json"
}
Body:
{
  "field": "value"
}
Capture:
- response.json.id -> created_id
Expected:
- HTTP 200
- response JSON exists
- response contains field "id"

### Step 2
Type: db
Name: <short-db-check-name>
SQL:
SELECT id, status
FROM some_table
WHERE id = :id
Params:
{
  "id": "{{created_id}}"
}
Expected:
- one row exists
- status = ACTIVE

## Final expectations
- all critical steps pass
- persisted state matches API results
- no unexpected blocker or runtime error occurs

## Report output
artifacts/agent/<project-name>-<scenario-name>-report.md
