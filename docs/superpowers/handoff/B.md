# Handoff B: better-auth (password + optional OIDC)

## Environment variables
- `AUTH_DATABASE_URL` (new, optional): libpq URL for the better-auth tables, e.g. `postgresql://janus:...@postgres:5432/janus`.
  When unset, the Next server and `scripts/migrate-auth.mjs` derive it from `JANUS_DATABASE_URL` by dropping the driver suffix (`postgresql+psycopg://` -> `postgresql://`), so the `api` container needs nothing new.
- `JANUS_ADMIN_USERNAME` / `JANUS_ADMIN_PASSWORD` (new, optional): when both are set and `auth."user"` is empty at start-up, the migration script creates a local admin (`<name>@local.invalid`, role `admin`, `source = local`).
  The password is only used on that first start; afterwards manage users from Settings > Sign-in.
- `JANUS_SECRET_KEY` (new, optional but recommended): key material for the encrypted secrets stored in the DB (OIDC client secrets, Gotify token, SMTP password). When unset the backend falls back to `JANUS_INTERNAL_TOKEN`, so **rotating either one makes stored secrets unreadable** (they read back as unset and have to be entered again). `docker-compose.yml` does not pass it today, i.e. production uses the internal token.
- `AUTH_SECRET` and `AUTH_URL` keep their meaning (better-auth `secret` and `baseURL`). Changing `AUTH_SECRET` invalidates every session (users sign in again; the smoke test confirmed this).
- Optional, read by the **backend** only (the frontend gets OIDC providers and the allowlist from `GET /api/internal/auth-config`):
  - `AUTH_AUTHENTIK_ID`, `AUTH_AUTHENTIK_SECRET`, `AUTH_AUTHENTIK_ISSUER` (or the new names `JANUS_OIDC_ID`, `JANUS_OIDC_SECRET`, `JANUS_OIDC_ISSUER`, plus `JANUS_OIDC_NAME`, default `Authentik`): an env-defined OIDC provider with id `authentik`. Providers added or overridden in Settings are stored under the settings key `auth.config` (secrets encrypted). With none set, only password login exists.
  - `JANUS_ALLOWED_EMAILS`: comma-separated allowlist for OIDC users (editable in Settings). Local users are not subject to it.
  `docker-compose.yml` already passes the `AUTH_AUTHENTIK_*` and `JANUS_ALLOWED_EMAILS` names, so nothing has to change in production.
- `AUTH_TRUST_HOST` is a NextAuth leftover and is ignored; it can be dropped from the compose file.

## OIDC callback URL
- better-auth serves the OIDC callback at `/api/auth/callback/<provider id>`. For the env provider that is
  `https://${JANUS_HOST}/api/auth/callback/authentik`, the same path NextAuth used, so the redirect URI registered in Authentik should already match. Verify it in Authentik (Applications > Providers > janus > Redirect URIs) before deploying.
- Settings > Sign-in shows the callback URL of each provider.

## Database
- better-auth tables `user`, `session`, `account`, `verification` live in the Postgres schema `auth` (not managed by Alembic).
- `entrypoint.sh` (mode `api`) runs `node /app/frontend/scripts/migrate-auth.mjs` before `alembic upgrade head`: it creates the schema if missing and applies better-auth migrations; it is idempotent.
- Extra user column `source` (`local` | `oidc`, default `oidc`, not settable from sign-up input).
- **Backups:** the schema `auth` holds the users, password hashes and sessions; the backup must include it next to `public` (a `pg_dump` of the whole `janus` database does; a dump restricted with `-n public` does not).
- Local users get a synthetic e-mail `<username>@local.invalid` (better-auth requires an e-mail). `.invalid` is a reserved TLD: no mail is ever delivered there, and it cannot collide with a real IdP address.

## Behavior changes
- `next-auth` is removed. Auth endpoints are served by better-auth under `/api/auth/*`; e-mail sign-up is disabled.
- A local user may sign in unless banned. An OIDC user is created only when their e-mail is allowlisted, and every request re-checks the allowlist (`getAllowedSession`).
- First run: with no user in `auth."user"` every page redirects to `/setup`, which creates the first admin and signs them in. Once a user exists `/setup` redirects to `/login`.
- The last usable (not banned) admin cannot be deleted, banned or demoted. The Settings UI disables those buttons, and better-auth refuses the admin endpoints server-side (`400 cannot remove the last admin`).
- OIDC providers whose discovery URL does not answer are left out of the login page (logged as `auth: OIDC provider "<id>" left out`) and re-probed every 15 s; password login keeps working.
- The sign-in configuration is cached for 15 s; when the backend is unreachable the last good one is used (or none: no OIDC providers, empty allowlist), so password sign-in keeps working.

## Still to check by hand in production
Automated smoke (local, test DB) covered setup, password login, proxy, sign-out, last-admin guard and an unreachable OIDC provider; these need the real IdP:
1. **Authentik login:** after deploying, "Sign in with Authentik" completes and lands on `/` (confirms the redirect URI above and the client secret).
2. **Allowlist removal:** with an Authentik session open, remove your e-mail from the allowlist in Settings; within 15 s the next page load must land on `/login` (API calls answer 401). Note: the proxy redirects to `/login?callbackUrl=...` before the layout can add `?error=AccessDenied`, so the login page shows no "not allowed" message in this case; the session is rejected all the same. Put it back afterwards.
3. **Wrong discovery URL:** set a wrong issuer for the provider in Settings; `/login` must still open with the username/password form, and password login must work. Restore the issuer.
4. Before the first deploy, make sure the backup job includes the `auth` schema and that at least one local admin exists (via `/setup` or `JANUS_ADMIN_USERNAME`/`JANUS_ADMIN_PASSWORD`), so a broken IdP never locks you out.
