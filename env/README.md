Use Python 3.14+ for this QA tools workspace.

Each project should have its own env file in this directory, for example `env/my-project.env`.

Expected variables:
- `API_BASE_URL`
- `API_AUTH_TYPE` (`none`, `bearer`, or `basic`; defaults to `none`)
- `API_BEARER_TOKEN` when `API_AUTH_TYPE=bearer`
- `API_USERNAME` and `API_PASSWORD` when `API_AUTH_TYPE=basic`
- `DATABASE_URL`
- `DATABASE_USER`
- `DATABASE_PASSWORD`

Basic auth aliases are also accepted for compatibility:
- `API_BASIC_USERNAME` / `API_BASIC_PASSWORD`
- `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD`

Actor-scoped API profiles are also supported when a scenario variable sets `actor`.
Use the same base keys with an uppercase actor suffix:
- `API_BASE_URL__ADMIN`
- `API_AUTH_TYPE__ADMIN`
- `API_BEARER_TOKEN__ADMIN`
- `API_USERNAME__ADMIN`
- `API_PASSWORD__ADMIN`

Actor-scoped DB profiles follow the same pattern:
- `DATABASE_URL__ADMIN`
- `DATABASE_USER__ADMIN`
- `DATABASE_PASSWORD__ADMIN`
- `DB_USER__ADMIN`
- `DB_PASSWORD__ADMIN`
- `PGUSER__ADMIN`
- `PGPASSWORD__ADMIN`
- `POSTGRES_USER__ADMIN`
- `POSTGRES_PASSWORD__ADMIN`

Actor names normalize by uppercasing and replacing non-alphanumeric characters with `_`.
Example: `actor = literal:api-client` resolves actor-scoped keys like `API_BASE_URL__API_CLIENT`.

For DB access you can either:
- put credentials directly into `DATABASE_URL`
- or keep `DATABASE_URL` without credentials and set `DATABASE_USER` plus `DATABASE_PASSWORD`
