Each project should have its own env file in this directory, for example `env/my-project.env`.

Expected variables:
- `API_BASE_URL`
- `API_BEARER_TOKEN`
- `DATABASE_URL`
- `DATABASE_USER`
- `DATABASE_PASSWORD`

For DB access you can either:
- put credentials directly into `DATABASE_URL`
- or keep `DATABASE_URL` without credentials and set `DATABASE_USER` plus `DATABASE_PASSWORD`
