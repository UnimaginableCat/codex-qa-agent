# Scenario: leadflow-internal-users-full-flow

## Project
code/LeadFlow

## Environment
env/LeadFlow.env

## Goal
Verify the full business flow for internal user management in `InternalUserController`: create global users, read users, list users with filters and pagination, patch editable profile fields, validate status transitions, reject invalid state transitions, and confirm persisted DB state matches API responses.

## Preconditions
- API is running
- DB is reachable
- Liquibase migrations are applied at least through `024-create-user-sessions`
- `spring.jpa.hibernate.ddl-auto` is not `create` or `update`
- `users` table exists
- API client can call internal routes under `/api/internal/v1/users`
- If the deployed environment protects internal routes outside `InternalUserController`, a valid internal auth/config is available

## Variables
- run_suffix = generated:run_suffix
- email_suffix = derived:run_suffix|lower
- primary_display_name = template:AUTOTEST User Primary {{run_suffix}}
- primary_email_mixed_case = template:AUTOTEST.Primary.{{email_suffix}}@Example.COM
- primary_email_normalized = template:autotest.primary.{{email_suffix}}@example.com
- primary_updated_display_name = template:AUTOTEST User Primary Updated {{run_suffix}}
- primary_updated_email_mixed_case = template:AUTOTEST.Primary.Updated.{{email_suffix}}@Example.COM
- primary_updated_email_normalized = template:autotest.primary.updated.{{email_suffix}}@example.com
- secondary_display_name = template:AUTOTEST User Secondary {{run_suffix}}
- secondary_email = template:autotest.secondary.{{email_suffix}}@example.com
- no_email_display_name = template:AUTOTEST User No Email {{run_suffix}}
- invalid_display_name = template:AUTOTEST Invalid User {{run_suffix}}
- missing_user_id = generated:uuid

## Notes
- Base API prefix for this project: `/api/internal/v1/users`.
- `InternalUserController` currently does not declare `@ValidateInternalApiToken`.
- If the environment or gateway requires an internal token, API steps should send `X-Leadflow-Internal-Token` from runtime config.
- The agent must not use JWT or bearer token auth for this controller-level scenario unless an external gateway explicitly requires it.
- If required internal auth/config is missing or invalid, API steps must be marked as `BLOCKED`.
- This is a full-flow scenario, so the agent should continue after successful capture and must not reuse stale IDs from previous runs.
- All created user-facing values in this scenario should include `{{run_suffix}}` to avoid collisions between runs.
- All email values and email assertions must use `{{email_suffix}}`, because application-side normalization lowercases the full email string, including the dynamic suffix.
- Expected DB tables:
  - `users`
- Related tables not managed by `InternalUserController`:
  - `user_identities`
  - `user_sessions`
- `UserStatus` enum values are `ACTIVE`, `SUSPENDED`, and `ARCHIVED`.
- `IdentityProvider` and identity endpoints are covered by `InternalUserIdentityController`, not by this scenario.
- There is no DELETE endpoint in `InternalUserController`; archival is the terminal user lifecycle operation.
- Response fields use JSON camelCase: `id`, `displayName`, `email`, `status`, `createdAt`, `updatedAt`.
- Nullable response fields can be returned as JSON `null` or omitted depending on ObjectMapper inclusion settings; DB checks are authoritative for nullable persistence.
- Scenario intentionally avoids API expectations of the form `is null or omitted`; nullable email behavior is asserted through DB checks because the runner DSL does not support that combined API rule.
- Scenario intentionally avoids root-array membership assertions for list endpoints and free-form error-message assertions for negative cases; current runner DSL support is limited to HTTP status, `response JSON exists`, field presence, equality, and null checks. List and negative-flow semantics are therefore asserted through status codes plus DB verification.
- Explicit `Retry:` blocks are not enabled in this scenario because the checked API operations are not known timeout-prone.

## Steps

### Step 1
Type: db
Name: verify-users-schema-ready
SQL:
```sql
SELECT
    (SELECT COUNT(*)
     FROM information_schema.columns
     WHERE table_name = 'users'
       AND column_name IN ('id', 'display_name', 'email', 'status', 'created_at', 'updated_at')) AS expected_column_count,
    (SELECT COUNT(*)
     FROM information_schema.table_constraints
     WHERE table_name = 'users'
       AND constraint_name = 'chk_users_status') AS status_constraint_count,
    (SELECT COUNT(*)
     FROM pg_indexes
     WHERE tablename = 'users'
       AND indexname IN ('idx_users_status', 'idx_users_created_at', 'idx_users_email')) AS expected_index_count;
```
Params:
```json
{}
```
Expected:
- one row exists
- `expected_column_count = 6`
- `status_constraint_count = 1`
- `expected_index_count = 3`

### Step 2
Type: api
Name: create-primary-user
Method: POST
Path: /api/internal/v1/users
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "  {{primary_display_name}}  ",
  "email": "  {{primary_email_mixed_case}}  "
}
```
Capture:
- response.json.id -> primary_user_id
- response.json.displayName -> primary_created_display_name
- response.json.email -> primary_created_email
- response.json.status -> primary_created_status
- response.json.createdAt -> primary_created_at
- response.json.updatedAt -> primary_updated_at_initial
Expected:
- HTTP 201
- response JSON exists
- response contains `id`
- response `displayName` = `{{primary_display_name}}`
- response `email` = `{{primary_email_normalized}}`
- response `status` = `ACTIVE`
- response contains `createdAt`
- response contains `updatedAt`
- response `createdAt` is not null
- response `updatedAt` is not null

### Step 3
Type: db
Name: verify-primary-user-created
SQL:
```sql
SELECT
    id,
    display_name,
    email,
    status,
    created_at,
    updated_at
FROM users
WHERE id = :primary_user_id;
```
Params:
```json
{
  "primary_user_id": "{{primary_user_id}}"
}
```
Expected:
- one row exists
- `id = {{primary_user_id}}`
- `display_name = {{primary_display_name}}`
- `email = {{primary_email_normalized}}`
- `status = ACTIVE`
- `created_at is not null`
- `updated_at is not null`

### Step 4
Type: api
Name: get-primary-user
Method: GET
Path: /api/internal/v1/users/{{primary_user_id}}
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists
- response `id` = `{{primary_user_id}}`
- response `displayName` = `{{primary_display_name}}`
- response `email` = `{{primary_email_normalized}}`
- response `status` = `ACTIVE`
- response contains `createdAt`
- response contains `updatedAt`

### Step 5
Type: api
Name: create-secondary-user
Method: POST
Path: /api/internal/v1/users
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "{{secondary_display_name}}",
  "email": "{{secondary_email}}"
}
```
Capture:
- response.json.id -> secondary_user_id
Expected:
- HTTP 201
- response JSON exists
- response contains `id`
- response `displayName` = `{{secondary_display_name}}`
- response `email` = `{{secondary_email}}`
- response `status` = `ACTIVE`

### Step 6
Type: api
Name: create-user-with-null-email
Method: POST
Path: /api/internal/v1/users
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "{{no_email_display_name}}",
  "email": null
}
```
Capture:
- response.json.id -> no_email_user_id
Expected:
- HTTP 201
- response JSON exists
- response contains `id`
- response `displayName` = `{{no_email_display_name}}`
- response `status` = `ACTIVE`

### Step 7
Type: db
Name: verify-user-with-null-email
SQL:
```sql
SELECT id, display_name, email, status
FROM users
WHERE id = :no_email_user_id;
```
Params:
```json
{
  "no_email_user_id": "{{no_email_user_id}}"
}
```
Expected:
- one row exists
- `id = {{no_email_user_id}}`
- `display_name = {{no_email_display_name}}`
- `email is null`
- `status = ACTIVE`

### Step 8
Type: api
Name: list-users-default
Method: GET
Path: /api/internal/v1/users
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists

### Step 9
Type: api
Name: list-active-users-by-email-query
Method: GET
Path: /api/internal/v1/users?status=ACTIVE&query=primary.{{email_suffix}}&limit=10&offset=0
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists

### Step 10
Type: api
Name: list-active-users-by-display-name-query
Method: GET
Path: /api/internal/v1/users?status=ACTIVE&query=No%20Email%20{{run_suffix}}&limit=10&offset=0
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists

### Step 11
Type: api
Name: list-users-pagination-limit-one
Method: GET
Path: /api/internal/v1/users?limit=1&offset=0
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists

### Step 12
Type: api
Name: update-primary-user-clear-email
Method: PATCH
Path: /api/internal/v1/users/{{primary_user_id}}
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "  {{primary_updated_display_name}}  ",
  "email": null
}
```
Capture:
- response.json.updatedAt -> primary_updated_at_after_clear_email
Expected:
- HTTP 200
- response JSON exists
- response `id` = `{{primary_user_id}}`
- response `displayName` = `{{primary_updated_display_name}}`
- response `status` = `ACTIVE`
- response `updatedAt` is not null

### Step 13
Type: db
Name: verify-primary-user-email-cleared
SQL:
```sql
SELECT display_name, email, status, updated_at
FROM users
WHERE id = :primary_user_id;
```
Params:
```json
{
  "primary_user_id": "{{primary_user_id}}"
}
```
Expected:
- one row exists
- `display_name = {{primary_updated_display_name}}`
- `email is null`
- `status = ACTIVE`
- `updated_at is not null`

### Step 14
Type: api
Name: update-primary-user-email-only
Method: PATCH
Path: /api/internal/v1/users/{{primary_user_id}}
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "email": "  {{primary_updated_email_mixed_case}}  "
}
```
Expected:
- HTTP 200
- response JSON exists
- response `id` = `{{primary_user_id}}`
- response `displayName` = `{{primary_updated_display_name}}`
- response `email` = `{{primary_updated_email_normalized}}`
- response `status` = `ACTIVE`

### Step 15
Type: db
Name: verify-primary-user-email-normalized-after-patch
SQL:
```sql
SELECT display_name, email, status
FROM users
WHERE id = :primary_user_id;
```
Params:
```json
{
  "primary_user_id": "{{primary_user_id}}"
}
```
Expected:
- one row exists
- `display_name = {{primary_updated_display_name}}`
- `email = {{primary_updated_email_normalized}}`
- `status = ACTIVE`

### Step 16
Type: api
Name: patch-primary-user-empty-body-noop
Method: PATCH
Path: /api/internal/v1/users/{{primary_user_id}}
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists
- response `id` = `{{primary_user_id}}`
- response `displayName` = `{{primary_updated_display_name}}`
- response `email` = `{{primary_updated_email_normalized}}`
- response `status` = `ACTIVE`

### Step 17
Type: api
Name: suspend-primary-user
Method: POST
Path: /api/internal/v1/users/{{primary_user_id}}/suspend
Headers:
```json
{}
```
Capture:
- response.json.updatedAt -> primary_updated_at_after_suspend
Expected:
- HTTP 200
- response JSON exists
- response `id` = `{{primary_user_id}}`
- response `status` = `SUSPENDED`
- response `updatedAt` is not null

### Step 18
Type: db
Name: verify-primary-user-suspended
SQL:
```sql
SELECT status
FROM users
WHERE id = :primary_user_id;
```
Params:
```json
{
  "primary_user_id": "{{primary_user_id}}"
}
```
Expected:
- one row exists
- `status = SUSPENDED`

### Step 19
Type: api
Name: list-suspended-users-by-query
Method: GET
Path: /api/internal/v1/users?status=SUSPENDED&query=Updated%20{{run_suffix}}&limit=10&offset=0
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists

### Step 20
Type: api
Name: activate-primary-user
Method: POST
Path: /api/internal/v1/users/{{primary_user_id}}/activate
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists
- response `id` = `{{primary_user_id}}`
- response `status` = `ACTIVE`

### Step 21
Type: db
Name: verify-primary-user-reactivated
SQL:
```sql
SELECT status
FROM users
WHERE id = :primary_user_id;
```
Params:
```json
{
  "primary_user_id": "{{primary_user_id}}"
}
```
Expected:
- one row exists
- `status = ACTIVE`

### Step 22
Type: api
Name: archive-primary-user
Method: POST
Path: /api/internal/v1/users/{{primary_user_id}}/archive
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists
- response `id` = `{{primary_user_id}}`
- response `status` = `ARCHIVED`

### Step 23
Type: db
Name: verify-primary-user-archived
SQL:
```sql
SELECT status
FROM users
WHERE id = :primary_user_id;
```
Params:
```json
{
  "primary_user_id": "{{primary_user_id}}"
}
```
Expected:
- one row exists
- `status = ARCHIVED`

### Step 24
Type: api
Name: get-archived-primary-user
Method: GET
Path: /api/internal/v1/users/{{primary_user_id}}
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists
- response `id` = `{{primary_user_id}}`
- response `displayName` = `{{primary_updated_display_name}}`
- response `email` = `{{primary_updated_email_normalized}}`
- response `status` = `ARCHIVED`

### Step 25
Type: api
Name: list-archived-users-by-query
Method: GET
Path: /api/internal/v1/users?status=ARCHIVED&query=Updated%20{{run_suffix}}&limit=10&offset=0
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists

### Step 26
Type: api
Name: update-archived-user-rejected
Method: PATCH
Path: /api/internal/v1/users/{{primary_user_id}}
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "AUTOTEST Should Not Update {{run_suffix}}"
}
```
Expected:
- HTTP 400

### Step 27
Type: db
Name: verify-archived-user-not-updated
SQL:
```sql
SELECT display_name, email, status
FROM users
WHERE id = :primary_user_id;
```
Params:
```json
{
  "primary_user_id": "{{primary_user_id}}"
}
```
Expected:
- one row exists
- `display_name = {{primary_updated_display_name}}`
- `email = {{primary_updated_email_normalized}}`
- `status = ARCHIVED`

### Step 28
Type: api
Name: activate-archived-user-rejected
Method: POST
Path: /api/internal/v1/users/{{primary_user_id}}/activate
Headers:
```json
{}
```
Expected:
- HTTP 400

### Step 29
Type: api
Name: suspend-archived-user-rejected
Method: POST
Path: /api/internal/v1/users/{{primary_user_id}}/suspend
Headers:
```json
{}
```
Expected:
- HTTP 400

### Step 30
Type: api
Name: archive-archived-user-idempotent
Method: POST
Path: /api/internal/v1/users/{{primary_user_id}}/archive
Headers:
```json
{}
```
Expected:
- HTTP 200
- response JSON exists
- response `id` = `{{primary_user_id}}`
- response `status` = `ARCHIVED`

### Step 31
Type: api
Name: get-missing-user
Method: GET
Path: /api/internal/v1/users/{{missing_user_id}}
Headers:
```json
{}
```
Expected:
- HTTP 404

### Step 32
Type: api
Name: update-missing-user
Method: PATCH
Path: /api/internal/v1/users/{{missing_user_id}}
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "AUTOTEST Missing User Update {{run_suffix}}"
}
```
Expected:
- HTTP 404

### Step 33
Type: api
Name: suspend-missing-user
Method: POST
Path: /api/internal/v1/users/{{missing_user_id}}/suspend
Headers:
```json
{}
```
Expected:
- HTTP 404

### Step 34
Type: api
Name: create-user-blank-display-name-rejected
Method: POST
Path: /api/internal/v1/users
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "   ",
  "email": "autotest.invalid.blank.{{email_suffix}}@example.com"
}
```
Expected:
- HTTP 400

### Step 35
Type: api
Name: create-user-too-long-display-name-rejected
Method: POST
Path: /api/internal/v1/users
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "{{invalid_display_name}} XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  "email": "autotest.invalid.longname.{{email_suffix}}@example.com"
}
```
Expected:
- HTTP 400

### Step 36
Type: api
Name: create-user-too-long-email-rejected
Method: POST
Path: /api/internal/v1/users
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "{{invalid_display_name}} Long Email",
  "email": "autotest.invalid.{{email_suffix}}.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx@example.com"
}
```
Expected:
- HTTP 400

### Step 37
Type: api
Name: update-user-blank-display-name-rejected
Method: PATCH
Path: /api/internal/v1/users/{{secondary_user_id}}
Headers:
```json
{
  "Content-Type": "application/json"
}
```
Body:
```json
{
  "displayName": "   "
}
```
Expected:
- HTTP 400

### Step 38
Type: db
Name: verify-secondary-user-not-updated-after-invalid-patch
SQL:
```sql
SELECT display_name, email, status
FROM users
WHERE id = :secondary_user_id;
```
Params:
```json
{
  "secondary_user_id": "{{secondary_user_id}}"
}
```
Expected:
- one row exists
- `display_name = {{secondary_display_name}}`
- `email = {{secondary_email}}`
- `status = ACTIVE`

### Step 39
Type: api
Name: list-users-limit-over-max-rejected
Method: GET
Path: /api/internal/v1/users?limit=101&offset=0
Headers:
```json
{}
```
Expected:
- HTTP 400

### Step 40
Type: api
Name: list-users-invalid-status-rejected
Method: GET
Path: /api/internal/v1/users?status=DELETED&limit=10&offset=0
Headers:
```json
{}
```
Expected:
- HTTP 400

### Step 41
Type: api
Name: get-user-invalid-uuid-rejected
Method: GET
Path: /api/internal/v1/users/not-a-uuid
Headers:
```json
{}
```
Expected:
- HTTP 400

### Step 42
Type: db
Name: verify-invalid-create-requests-did-not-persist-users
SQL:
```sql
SELECT COUNT(*) AS invalid_user_count
FROM users
WHERE display_name LIKE 'AUTOTEST Invalid User ' || :run_suffix || '%'
   OR email IN (
        'autotest.invalid.blank.' || :email_suffix || '@example.com',
        'autotest.invalid.longname.' || :email_suffix || '@example.com'
   );
```
Params:
```json
{
  "run_suffix": "{{run_suffix}}",
  "email_suffix": "{{email_suffix}}"
}
```
Expected:
- one row exists
- `invalid_user_count = 0`

## Final expectations
- `users` schema is present and constrained by the expected status enum check
- creating a user returns HTTP 201 and persists a UUID-backed global internal user
- `displayName` is trimmed before persistence
- `email` is optional, trimmed, and normalized to lowercase before persistence
- created users start in `ACTIVE` status
- `GET /api/internal/v1/users/{userId}` returns the persisted user
- `GET /api/internal/v1/users` returns HTTP 200 for the default, filtered, and paginated list requests used in this scenario
- because the runner cannot assert root-array contents, list-oriented semantics are cross-checked through surrounding persisted DB state
- `PATCH /api/internal/v1/users/{userId}` updates only fields present in the request body
- `PATCH` with `email: null` clears the persisted email
- `PATCH` with an empty JSON body is a no-op that returns the current user
- `POST /suspend` changes `ACTIVE -> SUSPENDED`
- `POST /activate` changes `SUSPENDED -> ACTIVE`
- `POST /archive` changes active or suspended users to `ARCHIVED`
- archived users remain readable and listable
- archived users cannot be patched
- archived users cannot be activated or suspended
- archiving an already archived user remains idempotent
- missing users return HTTP 404 for read, patch, and status-change operations
- invalid payloads return HTTP 400 and do not create or mutate persisted users
- invalid list parameters return HTTP 400
- invalid UUID path variables return HTTP 400
- persisted DB state matches API results across the flow

## Report output
artifacts/agent/leadflow-internal-users-full-flow-report.md
