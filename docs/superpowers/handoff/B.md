# Handoff B: better-auth (password + optional OIDC)

## Environment variables
- `AUTH_DATABASE_URL` (new, optional): libpq URL for the better-auth tables, e.g. `postgresql://janus:...@postgres:5432/janus`.
  When unset, the Next server and `scripts/migrate-auth.mjs` derive it from `JANUS_DATABASE_URL` by dropping the driver suffix (`postgresql+psycopg://` -> `postgresql://`), so the `api` container needs nothing new.
- `JANUS_ADMIN_USERNAME` / `JANUS_ADMIN_PASSWORD` (new, optional): when both are set and `auth."user"` is empty at start-up, the migration script creates a local admin (`<name>@local.invalid`, role `admin`, `source = local`).
- `AUTH_SECRET` and `AUTH_URL` keep their meaning (better-auth `secret` and `baseURL`).
- `AUTH_AUTHENTIK_*` and `JANUS_ALLOWED_EMAILS` are no longer read by the frontend (OIDC providers and the allowlist come from `GET /api/internal/auth-config`). `docker-compose.yml` still passes them.

## Database
- better-auth tables `user`, `session`, `account`, `verification` live in the Postgres schema `auth` (not managed by Alembic).
- `entrypoint.sh` (mode `api`) runs `node /app/frontend/scripts/migrate-auth.mjs` before `alembic upgrade head`: it creates the schema if missing and applies better-auth migrations; it is idempotent.
- Extra user column `source` (`local` | `oidc`, default `oidc`, not settable from sign-up input).

## Behavior changes
- `next-auth` is removed. Auth endpoints are served by better-auth under `/api/auth/*`; e-mail sign-up is disabled.
- A local user may sign in unless banned. An OIDC user is created only when their e-mail is allowlisted, and every request re-checks the allowlist (`getAllowedSession`).
- The sign-in configuration is cached for 15 s; when the backend is unreachable the last good one is used (or none: no OIDC providers, empty allowlist), so password sign-in keeps working.
