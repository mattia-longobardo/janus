# Flussi A e B — Integrazioni opzionali e better-auth: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (A) Gotify ed e-mail diventano opzionali e configurabili da Settings: se non sono configurati, le parti del sito che ne dipendono si spengono. (B) NextAuth+Authentik viene sostituito da better-auth: login con utente e password sempre disponibile, provider OIDC (Authentik o altri) configurabili da env o da Settings.

**Architecture:** (A) Due `OverlayStore` (`notify.gotify`, `notify.email`); il worker ricostruisce i sender **a ogni dispatch** leggendo il DB, così una modifica in Settings vale subito. `features["notify"]` dice quali canali sono pronti. (B) better-auth gira nel server Next, con tabelle nello schema Postgres `auth` (D3). La configurazione OIDC e l'allowlist stanno nel backend (`auth.config`, segreti cifrati) e il server Next le legge da `/api/internal/auth-config`. L'istanza better-auth viene ricostruita quando la configurazione cambia. Il backend continua a fidarsi solo del token interno.

**Tech Stack:** FastAPI, `OverlayStore` (flusso F), better-auth (≥1.3; plugin `username`, `admin`, `genericOAuth`, `nextCookies`), `pg`, Next.js 16 `proxy.ts` (runtime Node).

**Spec:** `docs/superpowers/plans/2026-10-03-00-orchestration.md` (requisiti 1 e 2; decisioni D1–D5; Review Focus 1, 2, 4 e 5).

## Global Constraints

- A: branch `feat/integrations`; B: branch `feat/auth`. Entrambi partono da `main` con F già incluso.
- A e B non creano migrazioni Alembic.
- B rimuove del tutto `next-auth` da `package.json`.
- Nessun segreto in chiaro nelle risposte delle rotte non-`internal`.
- Ognuno dei due flussi scrive le proprie note in `docs/superpowers/handoff/A.md` o `B.md`: variabili nuove o rimosse, comportamento cambiato.

## Review Focus

1. A: `JANUS_SMTP_HOST` aveva il default `mx.longobardo.me`. Il default va tolto, altrimenti la mail risulta sempre "configurata". In produzione `SMTP_HOST` è già passato dal compose del worker: da verificare nell'handoff. → test in A1.
2. A: si modifica il token Gotify in Settings mentre il worker gira; il dispatch successivo deve usare il token nuovo senza riavvio. → test in A1.
3. B: l'IdP OIDC è irraggiungibile o il discovery URL è sbagliato. La pagina di login deve comunque mostrare il form utente/password e il login locale deve funzionare. → test in B4.
4. B: si toglie un'e-mail dall'allowlist mentre l'utente OIDC ha una sessione aperta; alla richiesta successiva la sessione deve essere rifiutata (come oggi). → test in B3.
5. B: l'ultimo amministratore non può cancellarsi né togliersi il ruolo di admin. → test in B5.

---

## Parte A — Gotify ed e-mail opzionali

### Task A1: Configurazione dei canali da DB, sender ricostruiti a ogni dispatch

**Files:**
- Create: `backend/app/notify/config.py`
- Modify: `backend/app/config.py` (`smtp_host: str = ""`; nuovo campo `smtp_security: Literal["ssl","starttls","none"] = "ssl"`), `backend/app/notify/channels.py` (`EmailChannel` accetta `security`), `backend/app/worker.py` (`build_senders(db)`; `dispatch_once` lo chiama a ogni giro)
- Test: `backend/tests/test_notify_config.py`, `backend/tests/test_notify_channels.py` (caso STARTTLS), `backend/tests/test_worker.py` (adattare)

**Interfaces:**
- Consumes: `OverlayStore`, `StoreField`, `SettingsError` (F1)
- Produces:
  - `notify.config.GOTIFY: OverlayStore`, con chiave `notify.gotify` e campi `url`, `token` (secret)
  - `notify.config.EMAIL: OverlayStore`, con chiave `notify.email` e campi `host`, `port: int`, `security`, `user`, `password` (secret), `sender`
  - `notify.config.build_senders(db: Session) -> dict[str, Sender]`
  - `notify.config.channel_ready(db: Session) -> dict[str, bool]`: `{"email": bool, "gotify": bool}`. L'e-mail è pronta se ha `host` e `sender` e c'è un destinatario (DB o `JANUS_NOTIFY_EMAIL`).
  - `worker.dispatch_once(session_factory, debouncer, now=None, *, sender_factory=build_senders)`. **Firma cambiata**: senza `senders`, i test passano `sender_factory=lambda db: {...}`.

- [ ] **Step 1: Test che fallisce**

```python
# backend/tests/test_notify_config.py
import pytest

from app.config import settings
from app.notify import config as nc
from app.notify.channels import EmailChannel, GotifyChannel
from app.settingsstore import SettingsError


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "test-token")
    for name, value in {"gotify_url": "", "gotify_token": "", "smtp_host": "", "smtp_sender": "",
                        "smtp_user": "", "smtp_password": "", "notify_email": ""}.items():
        monkeypatch.setattr(settings, name, value)


def test_nothing_configured_means_no_channel_ready(db):
    assert nc.channel_ready(db) == {"email": False, "gotify": False}


def test_settings_page_values_take_effect_without_restart(db):
    nc.GOTIFY.update(db, {"url": "https://gotify.example/", "token": "t1"})
    senders = nc.build_senders(db)
    assert isinstance(senders["gotify"], GotifyChannel)
    assert (senders["gotify"].url, senders["gotify"].token) == ("https://gotify.example", "t1")
    nc.GOTIFY.update(db, {"token": "t2"})
    assert nc.build_senders(db)["gotify"].token == "t2"
    assert nc.channel_ready(db)["gotify"] is True


def test_email_needs_host_sender_and_recipient(db, monkeypatch):
    nc.EMAIL.update(db, {"host": "smtp.example", "port": 587, "security": "starttls", "sender": "janus@example.org"})
    assert nc.channel_ready(db)["email"] is False
    monkeypatch.setattr(settings, "notify_email", "me@example.org")
    assert nc.channel_ready(db)["email"] is True
    email = nc.build_senders(db)["email"]
    assert isinstance(email, EmailChannel) and email.security == "starttls"


def test_invalid_values_are_refused(db):
    with pytest.raises(SettingsError, match="url:"):
        nc.GOTIFY.update(db, {"url": "gotify.example"})
    with pytest.raises(SettingsError, match="security:"):
        nc.EMAIL.update(db, {"security": "tls13"})
    with pytest.raises(SettingsError, match="port:"):
        nc.EMAIL.update(db, {"port": 70000})
```

E in `test_notify_channels.py`:

```python
def test_starttls_upgrades_before_login():
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout): calls.append(("connect", host, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): calls.append(("starttls",))
        def login(self, u, p): calls.append(("login", u))
        def send_message(self, m): calls.append(("send", m["To"]))

    ch = EmailChannel("smtp.example", 587, "u", "p", "janus@example.org", security="starttls", smtp_factory=FakeSMTP)
    ch.send(Message(title="t", body="b", priority=5, url=None), NotifySettings(email_recipient="me@example.org"))
    assert [c[0] for c in calls] == ["connect", "starttls", "login", "send"]
```

(Controllare la firma reale di `Message` in `app/notify/render.py` e adattare gli argomenti.)

- [ ] **Step 2: Verificare che fallisca**

Run: `scripts/test.sh tests/test_notify_config.py tests/test_notify_channels.py -v`
Expected: FAIL (`ModuleNotFoundError: app.notify.config`; `unexpected keyword argument 'security'`)

- [ ] **Step 3: Implementazione**

```python
# backend/app/notify/config.py
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.notify.channels import EmailChannel, GotifyChannel
from app.notify.store import load_notify_settings
from app.settingsstore import OverlayStore, SettingsError, StoreField


def _url(value: Any) -> str:
    text = str(value).strip().rstrip("/")
    if not text.startswith(("http://", "https://")):
        raise SettingsError("url: must start with http:// or https://")
    return text


def _port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise SettingsError("port: must be a number") from None
    if not 1 <= port <= 65535:
        raise SettingsError("port: must be between 1 and 65535")
    return port


def _security(value: Any) -> str:
    if value not in ("ssl", "starttls", "none"):
        raise SettingsError("security: must be ssl, starttls or none")
    return value


def _text(value: Any) -> str:
    return str(value).strip()


GOTIFY = OverlayStore("notify.gotify", [
    StoreField("url", lambda: settings.gotify_url, validate=_url),
    StoreField("token", lambda: settings.gotify_token, secret=True),
])

EMAIL = OverlayStore("notify.email", [
    StoreField("host", lambda: settings.smtp_host, validate=_text),
    StoreField("port", lambda: settings.smtp_port, validate=_port),
    StoreField("security", lambda: settings.smtp_security, validate=_security),
    StoreField("user", lambda: settings.smtp_user, validate=_text),
    StoreField("password", lambda: settings.smtp_password, secret=True),
    StoreField("sender", lambda: settings.smtp_sender, validate=_text),
])


def build_senders(db: Session) -> dict[str, Any]:
    g, e = GOTIFY.load(db), EMAIL.load(db)
    return {
        "email": EmailChannel(e["host"], e["port"], e["user"], e["password"], e["sender"], security=e["security"]),
        "gotify": GotifyChannel(g["url"], g["token"]),
    }


def channel_ready(db: Session) -> dict[str, bool]:
    ns = load_notify_settings(db)
    return {name: sender.ready(ns) for name, sender in build_senders(db).items()}
```

In `channels.py`, `EmailChannel.__init__` riceve `security: str = "ssl"` e `smtp_factory: Callable[..., Any] | None = None`. In `send`, la factory è `smtp_factory or (smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP)`, e dentro il `with` va chiamato `if self.security == "starttls": smtp.starttls()` prima del login. Il resto non cambia. Il default `smtp_factory` del costruttore oggi è `smtplib.SMTP_SSL`: i test esistenti che passano `smtp_factory=` continuano a funzionare.

In `worker.py`: eliminare `build_senders()` locale; `dispatch_once(session_factory, debouncer, now=None, *, sender_factory=build_senders)` apre la sessione, chiama `senders = sender_factory(db)` e poi `dispatch_pending(db, senders, ...)`. Nel `main()` il job diventa `lambda: dispatch_once(SessionLocal, debouncer)`. Nei test di `test_worker.py` che passavano `senders`, sostituire con `sender_factory=lambda db: senders`.

- [ ] **Step 4: Verificare che passi**

Run: `scripts/test.sh tests/test_notify_config.py tests/test_notify_channels.py tests/test_worker.py tests/test_dispatcher.py -v`
Expected: tutto passa

- [ ] **Step 5: Commit**

```bash
git add backend/app/notify/config.py backend/app/notify/channels.py backend/app/config.py backend/app/worker.py backend/tests
git commit -m "feat(notify): channels configurable at runtime; STARTTLS; no hardcoded SMTP host"
```

### Task A2: API delle integrazioni e feature `notify`

**Files:**
- Modify: `backend/app/api/notifications.py` (nuove rotte + 409 sul test), `backend/app/api/settings.py` (`channels` calcolato dagli store), `backend/app/features.py` (riga `"notify"`)
- Test: `backend/tests/test_api_notifications.py`

**Interfaces:**
- Consumes: `GOTIFY`, `EMAIL`, `channel_ready` (A1), `FEATURE_PROVIDERS` (F2)
- Produces:
  - `GET /api/notifications/channels` → `{"gotify": {"values": {...view}, "source": {...}, "ready": bool}, "email": {...}}`
  - `PUT /api/notifications/channels` con corpo `{"gotify"?: {campo: valore|null}, "email"?: {...}}` → stessa forma del GET; 422 con `"campo: messaggio"` se non valido; evento `settings.channels` con i **nomi** dei campi cambiati (mai i valori)
  - `POST /api/notifications/test/{channel}` → 409 `"<channel> is not configured"` se il canale non è pronto
  - `features["notify"] == channel_ready(db)`

- [ ] **Step 1: Test che fallisce**

```python
# in backend/tests/test_api_notifications.py
def test_channels_round_trip_never_returns_secrets(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "gotify_url", "")
    monkeypatch.setattr(settings, "gotify_token", "")
    r = client.put("/api/notifications/channels", json={"gotify": {"url": "https://g.example", "token": "s3cret"}})
    assert r.status_code == 200
    assert r.json()["gotify"]["values"] == {"url": "https://g.example", "token": True}
    assert r.json()["gotify"]["ready"] is True
    assert "s3cret" not in client.get("/api/notifications/channels").text
    assert client.get("/api/features").json()["notify"]["gotify"] is True


def test_invalid_channel_value_is_422(client):
    r = client.put("/api/notifications/channels", json={"email": {"port": "abc"}})
    assert r.status_code == 422 and "port:" in r.json()["detail"]


def test_test_send_on_unconfigured_channel_is_409(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "gotify_url", "")
    assert client.post("/api/notifications/test/gotify").status_code == 409
```

- [ ] **Step 2: Verificare che fallisca**

Run: `scripts/test.sh tests/test_api_notifications.py -v`
Expected: FAIL (404 su `/channels`, 202 invece di 409)

- [ ] **Step 3: Implementazione**

```python
# in backend/app/api/notifications.py
from app.notify.config import EMAIL, GOTIFY, channel_ready
from app.settingsstore import SettingsError

STORES = {"gotify": GOTIFY, "email": EMAIL}


class ChannelsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gotify: dict[str, Any] | None = None
    email: dict[str, Any] | None = None


def _channels(db: Session) -> dict[str, Any]:
    ready = channel_ready(db)
    return {name: {"values": store.view(db), "source": store.sources(db), "ready": ready[name]}
            for name, store in STORES.items()}


@router.get("/channels")
def get_channels(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _channels(db)


@router.put("/channels")
def put_channels(body: ChannelsPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    changed: dict[str, list[str]] = {}
    try:
        for name, patch in body.model_dump(exclude_none=True).items():
            STORES[name].update(db, patch)
            changed[name] = sorted(patch)
    except SettingsError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if changed:
        record_event(db, "settings.channels", None, {"changed": changed})
    db.commit()
    return _channels(db)
```

In `test_channel`, prima di `record_event`: `if not channel_ready(db)[channel]: raise HTTPException(status.HTTP_409_CONFLICT, f"{channel} is not configured")`.

In `features.py`: `from app.notify.config import channel_ready` e `FEATURE_PROVIDERS["notify"] = channel_ready` (scritto direttamente dentro il dict letterale).

In `api/settings.py` `_view`, il campo `channels` diventa `{"gotify_url": GOTIFY.load(db)["url"], "email_sender": EMAIL.load(db)["sender"]}`, così il frontend esistente continua a funzionare.

- [ ] **Step 4: Verificare che passi**

Run: `scripts/test.sh tests/test_api_notifications.py tests/test_api_settings.py tests/test_api_features.py -v`
Expected: tutto passa

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/notifications.py backend/app/api/settings.py backend/app/features.py backend/tests/test_api_notifications.py
git commit -m "feat(api): edit notification channels; notify feature flag"
```

### Task A3: Frontend — Notifications nascosto se nessun canale, colonne solo per i canali pronti

**Files:**
- Modify: `frontend/lib/nav.ts` (`requires` sulla voce Notifications), `frontend/app/(app)/notifications/page.tsx`, `frontend/app/(app)/notifications/rules-table.tsx`
- Test: `frontend/app/(app)/notifications/rules.test.tsx`, `frontend/lib/nav.test.ts`

**Interfaces:**
- Consumes: `useFeatures()` (F3), `features.notify`
- Produces: `RulesTable` riceve la prop `channels: ("email" | "gotify")[]` e mostra solo quelle colonne

- [ ] **Step 1: Test che fallisce**

```ts
// aggiungere a frontend/lib/nav.test.ts
it("hides Notifications when no channel is ready", () => {
  expect(visibleNav({ notify: { email: false, gotify: false } }).some((i) => i.href === "/notifications")).toBe(false);
  expect(visibleNav({ notify: { email: false, gotify: true } }).some((i) => i.href === "/notifications")).toBe(true);
});
```

```tsx
// aggiungere a rules.test.tsx (usare il setup di render già presente nel file)
it("renders only the columns of ready channels", () => {
  renderRules({ channels: ["gotify"] });
  expect(screen.queryByRole("columnheader", { name: /e-mail/i })).toBeNull();
  expect(screen.getByRole("columnheader", { name: /gotify/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Verificare che fallisca** — Run: `cd frontend && npx vitest run lib/nav.test.ts "app/(app)/notifications"` → FAIL

- [ ] **Step 3: Implementazione**

In `nav.ts`, voce Notifications: `requires: (f) => Boolean(f.notify?.email || f.notify?.gotify)`.

In `page.tsx`: `const { features } = useFeatures(); const channels = (["email", "gotify"] as const).filter((c) => features?.notify?.[c]);`. Se `channels.length === 0` mostrare `<Notice>` con testo "No notification channel is configured. Add Gotify or e-mail in Settings → Integrations." e un `Link` a `/settings#integrations`, poi `return`. Altrimenti passare `channels` a `RulesTable` e alle card dei canali, che vanno tolte quando il canale non è pronto. I pulsanti "Send test" restano solo per i canali pronti. In `rules-table.tsx` le colonne email e gotify vengono generate da `channels.map(...)`.

- [ ] **Step 4: Verificare che passi** — Run: `cd frontend && npm test && npx tsc --noEmit` → tutto verde

- [ ] **Step 5: Commit** — `git commit -m "feat(web): hide notifications when no channel is configured"`

### Task A4: Frontend — sezione Settings "Integrations"

**Files:**
- Create: `frontend/app/(app)/settings/sections/integrations.tsx`, `frontend/app/(app)/settings/sections/integrations.test.tsx`, `frontend/lib/secret-input.tsx` (riusato poi da B e C)
- Modify: `frontend/app/(app)/settings/sections/index.ts` (una riga), `frontend/lib/types.ts` (blocco `// --- A ---`)

**Interfaces:**
- Consumes: `GET/PUT /api/notifications/channels` (A2), `api`, `useResource`, `useFeatures().reload`
- Produces:
  - `types.ts`: `ChannelState<V> = { values: V; source: Record<keyof V, "env" | "custom">; ready: boolean }`, `ChannelsView = { gotify: ChannelState<{ url: string; token: boolean }>; email: ChannelState<{ host: string; port: number; security: "ssl" | "starttls" | "none"; user: string; password: boolean; sender: string }> }`
  - `secret-input.tsx`: `SecretInput({ label, isSet, onChange })`. Mostra "•••• set" e un pulsante "Change"; `onChange(value: string | undefined)`: `undefined` = invariato, `""` = svuota, altro = nuovo valore.
  - Voce di registro: `{ id: "integrations", title: "Integrations", Component: IntegrationsSection }`

- [ ] **Step 1: Test che fallisce**

```tsx
// frontend/app/(app)/settings/sections/integrations.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { IntegrationsSection } from "./integrations";

const VIEW = {
  gotify: { values: { url: "", token: false }, source: { url: "env", token: "env" }, ready: false },
  email: { values: { host: "", port: 465, security: "ssl", user: "", password: false, sender: "" },
           source: { host: "env", port: "env", security: "env", user: "env", password: "env", sender: "env" }, ready: false },
};

describe("IntegrationsSection", () => {
  it("sends only the fields the user changed, secrets included", async () => {
    vi.spyOn(api, "get").mockResolvedValue(VIEW);
    const put = vi.spyOn(api, "put").mockResolvedValue({ ...VIEW, gotify: { ...VIEW.gotify, ready: true } });
    render(<IntegrationsSection />);
    await userEvent.type(await screen.findByLabelText("Gotify URL"), "https://g.example");
    await userEvent.click(screen.getByRole("button", { name: "Change Gotify token" }));
    await userEvent.type(screen.getByLabelText("Gotify token"), "tok");
    await userEvent.click(screen.getByRole("button", { name: "Save integrations" }));
    expect(put).toHaveBeenCalledWith("/notifications/channels", { gotify: { url: "https://g.example", token: "tok" } });
    expect(await screen.findByText(/Gotify · ready/)).toBeInTheDocument();
  });
});
```

(Se `useResource` non usa `api.get`, mockare `global.fetch` come negli altri test della cartella `components/`.)

- [ ] **Step 2: Verificare che fallisca** — Run: `cd frontend && npx vitest run "app/(app)/settings/sections/integrations.test.tsx"` → FAIL

- [ ] **Step 3: Implementazione** — Il componente carica `useResource<ChannelsView>("/notifications/channels")` e tiene `draft: { gotify: Partial<...>, email: Partial<...> }`. Ogni input usa `Field`/`inputClass` di `components/ui.tsx` e mostra il valore in uso (env o salvato, senza distinzioni a schermo). Non ci sono link "Reset to env": c'è un solo pulsante **Save**. Al salvataggio parte `api.put("/notifications/channels", pulito)`, dove "pulito" toglie i canali senza modifiche. Poi `setData(risposta)`, `useFeatures().reload()` (il menu si aggiorna subito) e un `Notice` "Saved". L'intestazione di ogni canale mostra `Gotify · ready` oppure `Gotify · not configured`, e un `Notice` 422 mostra il `detail` del backend. La sezione ha `id="integrations"` per l'ancora usata in A3.

- [ ] **Step 4: Verificare che passi** — Run: `cd frontend && npm test && npx tsc --noEmit`

- [ ] **Step 5: Commit** — `git commit -m "feat(web): configure Gotify and e-mail from Settings"`; scrivere `docs/superpowers/handoff/A.md` (default di `JANUS_SMTP_HOST` rimosso, nuovo `JANUS_SMTP_SECURITY`, rotte nuove).

---

## Parte B — better-auth

### Task B1: Backend — configurazione di login (allowlist e provider OIDC)

**Files:**
- Create: `backend/app/authconfig.py`, `backend/app/api/authconfig.py`
- Modify: `backend/app/api/internal.py` (rotta `GET /api/internal/auth-config`), `backend/app/config.py` (blocco `# --- B ---`: `allowed_emails: str = ""`; `oidc_id: str = ""`, `oidc_secret: str = ""`, `oidc_issuer: str = ""`, `oidc_name: str = "Authentik"`, con `validation_alias` agli env esistenti `AUTH_AUTHENTIK_ID`, `AUTH_AUTHENTIK_SECRET`, `AUTH_AUTHENTIK_ISSUER` tramite `AliasChoices`), `backend/app/main.py`
- Test: `backend/tests/test_authconfig.py`

**Interfaces:**
- Produces:
  - `authconfig.OidcProvider` (dataclass): `id: str` (slug `^[a-z0-9-]{2,32}$`), `name: str`, `discovery_url: str`, `client_id: str`, `client_secret: str`, `scopes: list[str]`, `enabled: bool`, `source: Literal["env","custom"]`
  - `authconfig.load(db) -> AuthConfig(allowed_emails: list[str], providers: list[OidcProvider])`. Se l'env Authentik è impostato, compare il provider con `id="authentik"` e `source="env"`; se un provider custom ha lo stesso id, vince il custom.
  - `authconfig.save(db, allowed_emails: list[str] | None, providers: list[dict]) -> AuthConfig`. Un `client_secret` assente o `None` mantiene il valore salvato.
  - `GET /api/settings/auth` → `{allowed_emails, allowed_emails_source, providers: [{..., client_secret: bool}]}`; `PUT /api/settings/auth` con la stessa forma (segreto opzionale).
  - `GET /api/internal/auth-config` → `{allowed_emails, providers: [{id, name, discovery_url, client_id, client_secret, scopes}], version}`, solo i provider abilitati e con i segreti in chiaro. `version` è un hash sha256 della configurazione: il frontend lo usa per sapere quando ricostruire l'istanza.
  - Storage: Setting `auth.config` = `{"allowed_emails": [...] | assente, "providers": [{..., "client_secret": "fernet:..."}]}`.

- [ ] **Step 1: Test che fallisce**

```python
# backend/tests/test_authconfig.py
import pytest

from app import authconfig
from app.config import settings


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "test-token")
    monkeypatch.setattr(settings, "allowed_emails", "a@example.org, B@example.org")
    monkeypatch.setattr(settings, "oidc_id", "cid")
    monkeypatch.setattr(settings, "oidc_secret", "csecret")
    monkeypatch.setattr(settings, "oidc_issuer", "https://auth.example/application/o/janus/")


def test_authentik_env_preconfigures_an_oidc_provider(db):
    cfg = authconfig.load(db)
    assert cfg.allowed_emails == ["a@example.org", "b@example.org"]
    [p] = cfg.providers
    assert (p.id, p.source, p.client_secret) == ("authentik", "env", "csecret")
    assert p.discovery_url == "https://auth.example/application/o/janus/.well-known/openid-configuration"


def test_no_env_means_password_only(db, monkeypatch):
    monkeypatch.setattr(settings, "oidc_id", "")
    assert authconfig.load(db).providers == []


def test_public_view_hides_secrets_internal_view_has_them(client):
    r = client.put("/api/settings/auth", json={"allowed_emails": ["c@example.org"], "providers": [
        {"id": "keycloak", "name": "Keycloak", "discovery_url": "https://kc.example/realms/home/.well-known/openid-configuration",
         "client_id": "janus", "client_secret": "kc-secret", "scopes": ["openid", "email", "profile"], "enabled": True}]})
    assert r.status_code == 200
    assert "kc-secret" not in r.text and "csecret" not in r.text
    internal = client.get("/api/internal/auth-config").json()
    assert {p["id"]: p["client_secret"] for p in internal["providers"]} == {"authentik": "csecret", "keycloak": "kc-secret"}
    assert internal["allowed_emails"] == ["c@example.org"]


def test_saving_without_secret_keeps_the_stored_one(client):
    body = {"providers": [{"id": "kc", "name": "KC", "discovery_url": "https://kc.example/.well-known/openid-configuration",
                           "client_id": "j", "client_secret": "one", "scopes": ["openid"], "enabled": True}]}
    client.put("/api/settings/auth", json=body)
    body["providers"][0].pop("client_secret")
    client.put("/api/settings/auth", json=body)
    secrets = {p["id"]: p["client_secret"] for p in client.get("/api/internal/auth-config").json()["providers"]}
    assert secrets["kc"] == "one"


def test_bad_provider_id_or_url_is_422(client):
    r = client.put("/api/settings/auth", json={"providers": [{"id": "Bad Id", "name": "x", "discovery_url": "nope",
                                                              "client_id": "j", "scopes": ["openid"], "enabled": True}]})
    assert r.status_code == 422
```

- [ ] **Step 2: Verificare che fallisca** — Run: `scripts/test.sh tests/test_authconfig.py -v` → FAIL (modulo mancante)

- [ ] **Step 3: Implementazione** — In `authconfig.py`, dataclass come sopra. `_env_provider()` costruisce il provider Authentik quando `settings.oidc_id` è impostato e aggiunge `.well-known/openid-configuration` all'issuer, se non c'è già. `load` legge il Setting, applica `secretbox.unseal` ai segreti e fonde i provider per id. `save` valida: id con regex, `discovery_url` che inizia con `https://` (oppure `http://` solo se l'host è un IP privato), `scopes` che contiene `openid`. I segreti si cifrano con `secretbox.seal`; quando il segreto è assente si conserva quello salvato. L'API (`api/authconfig.py`, prefisso `/api/settings/auth`) usa modelli Pydantic con `extra="forbid"`; un `ValueError` diventa un 422 con messaggio `"campo: …"`. In `features.py` **non** si aggiunge nulla: il login non dipende dalle feature del backend. Registrare il router in `main.py`.

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh tests/test_authconfig.py -v` → 5 passed

- [ ] **Step 5: Commit** — `git commit -m "feat(auth): sign-in configuration (OIDC providers, allowlist) with encrypted secrets"`

### Task B2: Frontend — istanza better-auth, schema `auth`, migrazione all'avvio

**Files:**
- Create: `frontend/lib/auth/config.ts`, `frontend/lib/auth/server.ts`, `frontend/lib/auth/client.ts`, `frontend/lib/auth/gate.ts`, `frontend/lib/auth/gate.test.ts`, `frontend/scripts/migrate-auth.mjs`, `frontend/app/api/auth/[...all]/route.ts`
- Delete: `frontend/auth.ts`, `frontend/app/api/auth/[...nextauth]/route.ts`, `frontend/lib/allowlist.ts` (la logica passa in `gate.ts`), `frontend/lib/allowlist.test.ts` (i casi vanno in `gate.test.ts`)
- Modify: `frontend/package.json` (togliere `next-auth`; aggiungere `better-auth`, `pg`, `@types/pg`), `entrypoint.sh` (modo `api`: `node /app/frontend/scripts/migrate-auth.mjs` prima di `alembic upgrade head`), `Dockerfile` (copiare `scripts/` e `node_modules/pg`/`better-auth` nello standalone; verificare che `output: "standalone"` li tracci, altrimenti aggiungerli a `serverExternalPackages` in `next.config.ts`)

**Interfaces:**
- Consumes: `GET /api/internal/auth-config` (B1), `backendHeaders()` da `lib/backend.ts`
- Produces:
  - `config.ts`: `type AuthConfig = { allowed_emails: string[]; providers: { id: string; name: string; discovery_url: string; client_id: string; client_secret: string; scopes: string[] }[]; version: string }`; `fetchAuthConfig(): Promise<AuthConfig>`, con cache in memoria di 15 s; se il backend non risponde restituisce l'ultima configurazione buona oppure `{ allowed_emails: [], providers: [], version: "offline" }`.
  - `server.ts`: `getAuth(): Promise<Auth>`, memoizzata su `config.version`; il `Pool` di `pg` è un singleton di modulo con `options: "-c search_path=auth"`. Inoltre `getSession(headers: Headers)` e `getAllowedSession(headers: Headers): Promise<{ user: { id; name; email; username?; role?; source } } | null>`.
  - `gate.ts` (puro, testabile): `isUserAllowed(user: { email?: string | null; source?: string | null; banned?: boolean | null }, allowedEmails: string[]): boolean`. Un utente `local` passa se non è bannato; un utente OIDC passa se l'e-mail, in minuscolo, è nell'allowlist.
  - `client.ts`: `authClient = createAuthClient({ plugins: [usernameClient(), adminClient()] })`.
  - Campo aggiuntivo dell'utente: `source: "local" | "oidc"` (`additionalFields`, `input: false`, default `"oidc"`). Gli utenti creati da `/setup` o dall'admin hanno `source: "local"`.

- [ ] **Step 1: Test che fallisce**

```ts
// frontend/lib/auth/gate.test.ts
import { describe, expect, it } from "vitest";

import { isUserAllowed } from "@/lib/auth/gate";

describe("isUserAllowed", () => {
  it("lets local users in unless banned", () => {
    expect(isUserAllowed({ source: "local", email: "x@local.invalid" }, [])).toBe(true);
    expect(isUserAllowed({ source: "local", banned: true }, [])).toBe(false);
  });

  it("checks OIDC users against the allowlist on every call, case-insensitively", () => {
    expect(isUserAllowed({ source: "oidc", email: "Me@Example.org" }, ["me@example.org"])).toBe(true);
    expect(isUserAllowed({ source: "oidc", email: "me@example.org" }, [])).toBe(false);
    expect(isUserAllowed({ source: "oidc", email: null }, ["me@example.org"])).toBe(false);
  });

  it("treats an unknown source as OIDC (safer default)", () => {
    expect(isUserAllowed({ email: "me@example.org" }, [])).toBe(false);
  });
});
```

- [ ] **Step 2: Verificare che fallisca** — Run: `cd frontend && npx vitest run lib/auth/gate.test.ts` → FAIL

- [ ] **Step 3: Implementazione**

```ts
// frontend/lib/auth/gate.ts
export type GateUser = { email?: string | null; source?: string | null; banned?: boolean | null };

export function isUserAllowed(user: GateUser, allowedEmails: string[]): boolean {
  if (user.banned) return false;
  if (user.source === "local") return true;
  const email = user.email?.trim().toLowerCase();
  return Boolean(email) && allowedEmails.map((e) => e.trim().toLowerCase()).includes(email!);
}
```

```ts
// frontend/lib/auth/server.ts
import "server-only";

import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { admin, genericOAuth, username } from "better-auth/plugins";
import { Pool } from "pg";

import { fetchAuthConfig, type AuthConfig } from "@/lib/auth/config";
import { isUserAllowed } from "@/lib/auth/gate";

const pool = new Pool({ connectionString: process.env.AUTH_DATABASE_URL, options: "-c search_path=auth" });

function build(cfg: AuthConfig) {
  return betterAuth({
    database: pool,
    secret: process.env.AUTH_SECRET,
    baseURL: process.env.AUTH_URL,
    session: { expiresIn: 12 * 60 * 60, updateAge: 60 * 60 },
    emailAndPassword: { enabled: true, disableSignUp: true },
    user: { additionalFields: { source: { type: "string", defaultValue: "oidc", input: false } } },
    databaseHooks: {
      user: {
        create: {
          before: async (user) => {
            const u = user as typeof user & { source?: string };
            // OIDC sign-ins create a user only when the e-mail is allowlisted.
            if (u.source !== "local" && !isUserAllowed(u, cfg.allowed_emails)) return false;
            return { data: user };
          },
        },
      },
    },
    plugins: [
      username(),
      admin({ defaultRole: "user" }),
      genericOAuth({
        config: cfg.providers.map((p) => ({
          providerId: p.id, discoveryUrl: p.discovery_url, clientId: p.client_id, clientSecret: p.client_secret, scopes: p.scopes,
        })),
      }),
      nextCookies(),
    ],
  });
}

export type Auth = ReturnType<typeof build>;
let cached: { version: string; auth: Auth } | null = null;

export async function getAuth(): Promise<Auth> {
  const cfg = await fetchAuthConfig();
  if (!cached || cached.version !== cfg.version) cached = { version: cfg.version, auth: build(cfg) };
  return cached.auth;
}

export async function getAllowedSession(headers: Headers) {
  const [auth, cfg] = [await getAuth(), await fetchAuthConfig()];
  const session = await auth.api.getSession({ headers });
  if (!session) return null;
  const user = session.user as typeof session.user & { source?: string; banned?: boolean | null };
  return isUserAllowed(user, cfg.allowed_emails) ? session : null;
}
```

```ts
// frontend/app/api/auth/[...all]/route.ts
import { toNextJsHandler } from "better-auth/next-js";

import { getAuth } from "@/lib/auth/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function handle(req: Request) {
  const { GET, POST } = toNextJsHandler(await getAuth());
  return req.method === "POST" ? POST(req) : GET(req);
}

export { handle as GET, handle as POST };
```

```js
// frontend/scripts/migrate-auth.mjs — runs once at container start, before the API.
import { betterAuth } from "better-auth";
import { getMigrations } from "better-auth/db/migration";
import { admin, username } from "better-auth/plugins";
import pg from "pg";

const url = process.env.AUTH_DATABASE_URL;
const bootstrap = new pg.Client({ connectionString: url });
await bootstrap.connect();
await bootstrap.query("CREATE SCHEMA IF NOT EXISTS auth");
await bootstrap.end();

const pool = new pg.Pool({ connectionString: url, options: "-c search_path=auth" });
const auth = betterAuth({
  database: pool,
  emailAndPassword: { enabled: true },
  user: { additionalFields: { source: { type: "string", defaultValue: "oidc", input: false } } },
  plugins: [username(), admin()],
});
const { runMigrations } = await getMigrations(auth.options);
await runMigrations();

const { JANUS_ADMIN_USERNAME: name, JANUS_ADMIN_PASSWORD: password } = process.env;
if (name && password) {
  const { rows } = await pool.query('SELECT count(*)::int AS n FROM "user"');
  if (rows[0].n === 0) {
    await auth.api.createUser({ body: { email: `${name}@local.invalid`, password, name, role: "admin",
                                        data: { username: name, source: "local" } } });
  }
}
await pool.end();
```

Note per l'implementer:
- Prima di scrivere il codice verificare la versione installata di better-auth e le firme di `genericOAuth`, `admin().createUser` e `databaseHooks` (doc: https://www.better-auth.com/docs/plugins/generic-oauth, https://www.better-auth.com/docs/plugins/admin, https://www.better-auth.com/docs/plugins/username). Se `createUser` non accetta `data.source` perché `input: false`, inserire l'utente e poi `UPDATE "user" SET source='local'`.
- La configurazione dei plugin in `migrate-auth.mjs` deve generare **le stesse colonne** di `server.ts`. Il reviewer lo verifica.
- `AUTH_DATABASE_URL`: nuova variabile (`postgresql://janus:...@postgres:5432/janus`). Se manca, derivarla da `JANUS_DATABASE_URL` togliendo il suffisso `+psycopg` dallo schema, sia in `config.ts` sia nello script. Annotarlo nell'handoff.

- [ ] **Step 4: Verificare che passi** — Run: `cd frontend && npm i && npx vitest run lib/auth && npx tsc --noEmit`. Poi lanciare `AUTH_DATABASE_URL=postgresql://janus:<pw>@localhost:5432/janus_test node scripts/migrate-auth.mjs` due volte (deve essere idempotente) e `psql ... -c '\dt auth.*'`, che deve mostrare `user`, `session`, `account`, `verification`.

- [ ] **Step 5: Commit** — `git commit -m "feat(auth): better-auth with password and generic OIDC, tables in the auth schema"`

### Task B3: Protezione di pagine e API con la nuova sessione

**Files:**
- Modify: `frontend/proxy.ts`, `frontend/app/(app)/layout.tsx`, `frontend/app/api/[...path]/route.ts`, `frontend/lib/auth-actions.ts`, `frontend/components/sidebar.tsx` (solo il form di logout)
- Test: `frontend/lib/auth/session-guard.test.ts`; creare `frontend/lib/auth/session-guard.ts`

**Interfaces:**
- Consumes: `getAllowedSession` (B2)
- Produces:
  - `session-guard.ts`: `decide(pathname: string, signedIn: boolean, hasUsers: boolean): { kind: "next" } | { kind: "json401" } | { kind: "redirect"; to: string }`. Senza utenti ogni pagina porta a `/setup`; `/setup` porta a `/login` se gli utenti esistono già.
  - `auth-actions.ts`: `logout()` chiama `(await getAuth()).api.signOut({ headers: await headers() })` e poi `redirect("/login")`.
  - `getHasUsers()` in `server.ts`: `SELECT EXISTS (SELECT 1 FROM auth."user")`, con cache di 10 s dopo il primo `true`.

- [ ] **Step 1: Test che fallisce**

```ts
// frontend/lib/auth/session-guard.test.ts
import { describe, expect, it } from "vitest";

import { decide } from "@/lib/auth/session-guard";

describe("decide", () => {
  it("sends everyone to /setup until the first user exists", () => {
    expect(decide("/devices", false, false)).toEqual({ kind: "redirect", to: "/setup" });
    expect(decide("/setup", false, false)).toEqual({ kind: "next" });
  });
  it("closes /setup once a user exists", () => {
    expect(decide("/setup", false, true)).toEqual({ kind: "redirect", to: "/login" });
  });
  it("answers 401 JSON for API calls and redirects pages with a callback", () => {
    expect(decide("/api/devices", false, true)).toEqual({ kind: "json401" });
    expect(decide("/groups?x=1", false, true)).toEqual({ kind: "redirect", to: "/login?callbackUrl=%2Fgroups%3Fx%3D1" });
  });
  it("lets signed-in users through", () => {
    expect(decide("/groups", true, true)).toEqual({ kind: "next" });
  });
});
```

- [ ] **Step 2: Verificare che fallisca** — Run: `cd frontend && npx vitest run lib/auth/session-guard.test.ts` → FAIL

- [ ] **Step 3: Implementazione** — `decide` è una funzione pura come sopra. `proxy.ts` diventa:

```ts
import { NextResponse, type NextRequest } from "next/server";

import { decide } from "@/lib/auth/session-guard";
import { getAllowedSession, getHasUsers } from "@/lib/auth/server";

export async function proxy(req: NextRequest) {
  const path = `${req.nextUrl.pathname}${req.nextUrl.search}`;
  const result = decide(path, Boolean(await getAllowedSession(req.headers)), await getHasUsers());
  if (result.kind === "next") return NextResponse.next();
  if (result.kind === "json401") return NextResponse.json({ detail: "not signed in" }, { status: 401 });
  return NextResponse.redirect(new URL(result.to, req.nextUrl.origin));
}

export const config = {
  matcher: ["/((?!api/auth(?:/|$)|api/healthz$|login$|_next/static/|_next/image(?:/|$)|favicon\\.ico$|icon\\.svg$|robots\\.txt$).*)"],
};
```

`(app)/layout.tsx` usa `getAllowedSession(await headers())`, altrimenti `redirect("/login?error=AccessDenied")`, e passa a `Shell` `user = session.user.username ?? session.user.name ?? session.user.email`. In `app/api/[...path]/route.ts`, `signedIn = Boolean(await getAllowedSession(req.headers))`.

Test di regressione per il Review Focus 4: in `gate.test.ts` c'è già il caso "allowlist rimossa → false". In più, test manuale nel task B6.

- [ ] **Step 4: Verificare che passi** — Run: `cd frontend && npm test && npx tsc --noEmit && npm run build`

- [ ] **Step 5: Commit** — `git commit -m "feat(auth): guard pages and API with better-auth sessions"`

### Task B4: Pagine `/login` e `/setup`

**Files:**
- Create: `frontend/app/setup/page.tsx`, `frontend/app/setup/actions.ts`, `frontend/app/login/login-form.tsx`, `frontend/app/login/login-form.test.tsx`
- Modify: `frontend/app/login/page.tsx`

**Interfaces:**
- Consumes: `authClient` (B2), `fetchAuthConfig` (B2), `getHasUsers` (B3)
- Produces:
  - `LoginForm({ providers: { id: string; name: string }[], error?: string, callbackUrl?: string })` (client component): form utente/password (`authClient.signIn.username`) e un pulsante "Sign in with {name}" per ogni provider (`authClient.signIn.social({ provider: id, callbackURL })`).
  - `setup/actions.ts`: `createFirstAdmin(formData)` (server action). Ricontrolla `getHasUsers()` (se è già `true` → `redirect("/login")`), crea l'utente con `role: "admin"` e `source: "local"`, poi fa login e `redirect("/")`. La password deve avere almeno 12 caratteri.

- [ ] **Step 1: Test che fallisce**

```tsx
// frontend/app/login/login-form.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const signIn = { username: vi.fn().mockResolvedValue({ error: null }), social: vi.fn() };
vi.mock("@/lib/auth/client", () => ({ authClient: { signIn } }));

import { LoginForm } from "./login-form";

describe("LoginForm", () => {
  it("always offers username and password even with no providers", async () => {
    render(<LoginForm providers={[]} />);
    await userEvent.type(screen.getByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(signIn.username).toHaveBeenCalledWith(expect.objectContaining({ username: "admin", password: "correct horse battery" }));
  });

  it("renders one button per configured OIDC provider", async () => {
    render(<LoginForm providers={[{ id: "authentik", name: "Authentik" }, { id: "kc", name: "Keycloak" }]} callbackUrl="/groups" />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in with Keycloak" }));
    expect(signIn.social).toHaveBeenCalledWith({ provider: "kc", callbackURL: "/groups" });
  });

  it("shows a readable message on wrong credentials", async () => {
    signIn.username.mockResolvedValueOnce({ error: { message: "Invalid username or password" } });
    render(<LoginForm providers={[]} />);
    await userEvent.type(screen.getByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password");
  });
});
```

- [ ] **Step 2: Verificare che fallisca** — Run: `cd frontend && npx vitest run app/login` → FAIL

- [ ] **Step 3: Implementazione** — `login/page.tsx` è un server component. Se `!(await getHasUsers())` fa `redirect("/setup")`; poi `providers = (await fetchAuthConfig()).providers.map(({ id, name }) => ({ id, name }))`. Il fallback offline di `fetchAuthConfig` restituisce `providers: []`: è questo che garantisce il Review Focus 3. Va mantenuto lo stile visivo della pagina di login attuale, ma senza testi specifici di Authentik. `/setup` ha un form con username, password e conferma, e mostra gli errori in un `Notice`. Il matcher di `proxy.ts` deve escludere anche `setup$`, perché `decide` gestisce già `/setup`: aggiornare la regex.

- [ ] **Step 4: Verificare che passi** — Run: `cd frontend && npm test && npx tsc --noEmit && npm run build`

- [ ] **Step 5: Commit** — `git commit -m "feat(auth): password + OIDC login page and first-run setup"`

### Task B5: Settings — "Sign-in & users"

**Files:**
- Create: `frontend/app/(app)/settings/sections/sign-in.tsx`, `frontend/app/(app)/settings/sections/sign-in.test.tsx`, `frontend/lib/auth/last-admin.ts`, `frontend/lib/auth/last-admin.test.ts`
- Modify: `frontend/app/(app)/settings/sections/index.ts` (una riga), `frontend/lib/types.ts` (blocco `// --- B ---`)

**Interfaces:**
- Consumes: `authClient.admin.listUsers/createUser/removeUser/setRole/setUserPassword`, `authClient.changePassword`, `GET/PUT /api/settings/auth` (B1), `SecretInput` (A4). Se B si fonde prima di A4, B crea `lib/secret-input.tsx` con la stessa firma e A4 lo riusa.
- Produces:
  - `last-admin.ts`: `canRemoveOrDemote(target: { id: string; role?: string | null }, users: { id: string; role?: string | null }[]): boolean`, `false` se il target è l'unico admin
  - Sezione `{ id: "sign-in", title: "Sign-in & users", Component: SignInSection }`. Le parti "Users" e "OIDC providers" sono visibili solo agli admin (`authClient.useSession().data?.user.role === "admin"`); "Change my password" è visibile a tutti gli utenti `local`.

- [ ] **Step 1: Test che fallisce**

```ts
// frontend/lib/auth/last-admin.test.ts
import { describe, expect, it } from "vitest";

import { canRemoveOrDemote } from "@/lib/auth/last-admin";

describe("canRemoveOrDemote", () => {
  const a = { id: "a", role: "admin" }, b = { id: "b", role: "admin" }, u = { id: "u", role: "user" };
  it("refuses to remove the only admin", () => expect(canRemoveOrDemote(a, [a, u])).toBe(false));
  it("allows it when another admin exists", () => expect(canRemoveOrDemote(a, [a, b, u])).toBe(true));
  it("always allows plain users", () => expect(canRemoveOrDemote(u, [a, u])).toBe(true));
});
```

```tsx
// frontend/app/(app)/settings/sections/sign-in.test.tsx (estratto)
it("disables Delete on the last admin", async () => {
  mockSession({ id: "a", role: "admin", source: "local" });
  mockUsers([{ id: "a", name: "admin", role: "admin" }, { id: "u", name: "kid", role: "user" }]);
  render(<SignInSection />);
  expect(await screen.findByRole("button", { name: "Delete admin" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Delete kid" })).toBeEnabled();
});
```

(`mockSession` e `mockUsers` sono helper locali al test e fanno `vi.mock("@/lib/auth/client")`.)

- [ ] **Step 2: Verificare che fallisca** — Run: `cd frontend && npx vitest run lib/auth/last-admin.test.ts "app/(app)/settings/sections/sign-in.test.tsx"` → FAIL

- [ ] **Step 3: Implementazione** — La sezione contiene:
  1. tabella degli utenti (username, origine local/OIDC, ruolo, azioni "Reset password", "Make admin/user", "Delete"), dove le azioni distruttive sono disabilitate quando `canRemoveOrDemote` è falso;
  2. form "Add user" (username, password ≥12, ruolo), con `authClient.admin.createUser({ email: \`${username}@local.invalid\`, password, name: username, role, data: { username, source: "local" } })`;
  3. "Allowed e-mails (OIDC)", una textarea con un indirizzo per riga;
  4. "OIDC providers", con lista modificabile (id, nome, discovery URL, client id, `SecretInput` per il secret, scopes, enabled), salvata con `api.put("/settings/auth", ...)`. Anche i provider che arrivano dall'env (es. Authentik da `AUTH_AUTHENTIK_*`) sono modificabili: salvandoli si crea un override con lo stesso id, come per gli altri campi (D1). Un unico pulsante **Save**. Sotto il form va mostrato il callback URL da copiare nell'IdP: `${location.origin}/api/auth/callback/<id>`;
  5. "Change my password" (`authClient.changePassword`).

- [ ] **Step 4: Verificare che passi** — Run: `cd frontend && npm test && npx tsc --noEmit`

- [ ] **Step 5: Commit** — `git commit -m "feat(web): manage users and OIDC providers from Settings"`

### Task B6: Verifica integrata del login (manuale, sullo stack di sviluppo)

- [ ] `docker compose build janus && docker compose up -d janus` su una copia dello stack con DB vuoto. Aprire `/`: si deve arrivare su `/setup`; creare l'admin; fare logout e login con password.
- [ ] Con gli `AUTH_AUTHENTIK_*` di produzione: il pulsante "Sign in with Authentik" funziona. Callback da registrare in Authentik: `https://${JANUS_HOST}/api/auth/callback/authentik` (prima era `/api/auth/callback/authentik` di NextAuth: va verificato che coincida e, se serve, aggiornato in Authentik; annotarlo nell'handoff).
- [ ] Togliere la propria e-mail dall'allowlist in Settings: la richiesta successiva deve portare a `/login?error=AccessDenied`.
- [ ] Impostare un discovery URL sbagliato: la pagina di login si apre comunque e il login con password funziona.
- [ ] Scrivere `docs/superpowers/handoff/B.md`: variabili nuove (`AUTH_DATABASE_URL`, `JANUS_ADMIN_USERNAME`, `JANUS_ADMIN_PASSWORD`, `JANUS_SECRET_KEY`), opzionali (`AUTH_AUTHENTIK_*`, `JANUS_ALLOWED_EMAILS`), callback URL e nuovo schema `auth` (da includere nei backup).
- [ ] Commit: `git commit -m "docs(handoff): better-auth notes"`
