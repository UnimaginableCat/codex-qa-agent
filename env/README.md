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

For DB access you can either:
- put credentials directly into `DATABASE_URL`
- or keep `DATABASE_URL` without credentials and set `DATABASE_USER` plus `DATABASE_PASSWORD`
