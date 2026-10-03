# Handoff A: optional Gotify and e-mail

## Environment variables
- `JANUS_SMTP_HOST`: the default `mx.longobardo.me` is removed (empty by default). With no host the e-mail channel is "not configured".
  Production already passes `SMTP_HOST` from the compose file for both `api` and `worker`, so nothing changes there; verify `SMTP_HOST` is set in `.env` before deploying.
- `JANUS_SMTP_SECURITY` (new): `ssl` (default) | `starttls` | `none`.
  The compose files still hard-code `JANUS_SMTP_PORT=465`, which matches the `ssl` default; set both when switching to STARTTLS (587).
- `JANUS_GOTIFY_URL` / `JANUS_GOTIFY_TOKEN`, `JANUS_SMTP_*`, `JANUS_NOTIFY_EMAIL` are now env defaults that Settings can override at runtime (overlay stores `notify.gotify`, `notify.email`; secrets encrypted).

## docker-compose.yml
- The `api` container now receives the full notify env (Gotify and SMTP variables), not only the worker, so `GET /api/notifications/channels` shows the env values as defaults.

## Routes
- `GET /api/notifications/channels` -> `{gotify: {values, source, ready}, email: {...}}`; secrets are returned as booleans.
- `PUT /api/notifications/channels`: partial body per channel; a value equal to the env value drops the override, `""` clears a value; 422 detail is `"field: message"`.
- `GET /api/features` now includes `notify: {gotify, email}` (ready flags).

## Behavior changes
- The worker rebuilds the senders on every dispatch from the DB, so a change in Settings applies without restart.
- When no channel is ready, the notification parts of the UI are hidden (nav and settings notice link to `/settings#integrations`).
- Settings has an "Integrations" card (`id="integrations"`): one Save button, no "Reset to env" links (D1).
- `frontend/lib/secret-input.tsx` is shared: `onChange(undefined)` = unchanged, `""` = clear, other = new value. Reused by B5 and C6.
