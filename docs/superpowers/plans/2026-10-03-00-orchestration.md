# Janus — Integrazioni opzionali, better-auth, ospiti, provider di rete: piano multi-agente

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each sub-plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere Janus installabile da chiunque: Gotify/e-mail/Authentik diventano opzionali e configurabili da Settings, il login passa a better-auth (utente+password più provider OIDC a scelta), nasce una sezione Ospiti con scadenze, e Pi-hole diventa uno dei possibili "provider di rete" (accanto a UniFi e a quelli che aggiungerà la community).

**Architecture:** Un livello di fondazione comune (overlay env→DB con segreti cifrati, endpoint `/api/features`, nav e Settings modulari) sblocca tre flussi paralleli (integrazioni, auth, provider). Su quest'ultimo poggiano UniFi e Ospiti. Ogni flusso lavora in un worktree proprio e ha file di sua proprietà esclusiva; i punti di contatto sono registri "una riga per voce" pensati per avere merge banali.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL (backend), Next.js 16 + React 19 + Tailwind 4 + Vitest (frontend), better-auth + `pg`, `cryptography` (Fernet), httpx + respx.

**Spec:** la richiesta dell'utente del 2026-10-03 (riportata sotto in "Requisiti") e le decisioni in "Decisioni prese".

## Requisiti (testo dell'utente, riassunto fedele)

1. **Integrazioni opzionali.** Gotify, e-mail, Authentik: se mancano le variabili, il sistema funziona lo stesso e le sezioni del sito che ne dipendono si spengono. Devono essere configurabili anche da Settings.
2. **better-auth.** Più metodi di login, anche solo utente e password; poi ognuno ci collega il servizio che preferisce.
3. **Ospiti.** MAC salvati senza IP assegnato. Esiste un pool di IP per gli ospiti. Dalla lista ospiti si può rimuovere un ospite. Un'impostazione globale opzionale rimuove gli ospiti dopo un certo tempo. Su ogni singolo ospite si può impostare una durata o una data dopo cui viene rimosso.
4. **Provider di rete.** Oggi tutto passa da Pi-hole; un amico userà UniFi, che offre più opzioni, quindi le pagine cambiano a seconda del provider scelto. Pi-hole si può affiancare a un router con API (es. UniFi) come solo DNS. La struttura delle cartelle deve permettere ad altri di aggiungere il proprio router.

## Decisioni prese (l'utente non era presente; ognuna è reversibile)

| # | Decisione | Perché |
|---|---|---|
| D1 | Le variabili d'ambiente restano il **default**. Settings mostra i valori in uso e ha un normale pulsante **Save**: ciò che salvi su DB vale sopra l'env. Non c'è un pulsante "Reset to env": un valore salvato uguale a quello dell'env non viene memorizzato, quindi quel campo torna a seguire l'env. È lo stesso modello già usato da `netconfig.py`, che salva solo le differenze. | Le installazioni esistenti non cambiano comportamento; non si introduce un secondo modello mentale. |
| D2 | I segreti salvati da UI (token Gotify, password SMTP, client secret OIDC, credenziali provider) sono cifrati con Fernet. La chiave è `JANUS_SECRET_KEY`; se manca, viene derivata con HKDF da `JANUS_INTERNAL_TOKEN`. Le API pubbliche non li restituiscono mai: mostrano solo `"set": true/false`. | Il DB è condiviso nell'homelab; un dump non deve contenere segreti in chiaro. |
| D3 | Le tabelle di better-auth vivono nello **stesso Postgres, schema `auth`**. Le crea `frontend/scripts/migrate-auth.mjs` (API `getMigrations` di better-auth) all'avvio del container `api`, prima di Alembic. | Alembic non tocca quelle tabelle e `test_migrations.py` resta valido. Non serve un DB nuovo. |
| D4 | Primo accesso: se non esiste nessun utente, `/setup` crea l'amministratore. In alternativa `JANUS_ADMIN_USERNAME`/`JANUS_ADMIN_PASSWORD` lo creano all'avvio. La registrazione libera è disattivata. | Funziona senza alcun IdP. |
| D5 | Authentik diventa un **provider OIDC generico** (discovery URL, client id/secret, nome). Gli `AUTH_AUTHENTIK_*` esistenti lo pre-configurano. `JANUS_ALLOWED_EMAILS` resta valido solo per gli utenti OIDC ed è verificato **a ogni richiesta**, come oggi. | Compatibilità e possibilità di collegare qualsiasi IdP (Authentik, Keycloak, Google, …). |
| D6 | Due regole globali di rimozione automatica, entrambe opzionali e combinabili: **(a)** N ore da quando il device è diventato ospite (`guest_since`); **(b)** N ore di **inattività**, cioè senza essere visto dal sentinel (`last_seen`, oppure `guest_since` se non è mai stato visto). L'ospite viene rimosso alla prima regola che scatta. Una scadenza impostata sul singolo ospite (`guest_expires_at`) sostituisce **entrambe** le regole globali per quell'ospite. | "Dopo un tot tempo" e "dopo un periodo di inattività", come richiesto; la scadenza scelta a mano per un ospite non deve essere annullata da una regola generale. |
| D7 | "Rimuovi ospite" cancella il device e revoca il lease. Se il device è ancora connesso, ricompare come `pending`. | Coerente con l'attuale DELETE dei device. |
| D8 | I provider hanno due **ruoli**: `dhcp` (prenotazioni, revoca lease, accesso) e `dns` (query log, sonda DNS). Ogni ruolo ha al massimo un provider. Configurazioni previste: **Pi-hole DNS+DHCP (oggi e default)**, UniFi DHCP + Pi-hole DNS, UniFi + nessun DNS, nessuno + nessuno (solo inventario). Quando lo stesso Pi-hole fa entrambi, il DNS è `same_as: "dhcp"`: una sola config, una sola sessione, nessuna copia che può divergere. Ogni ruolo espone solo le capability che gli appartengono: un Pi-hole solo DNS non accende quarantena né cutover. | Copre sia il caso di oggi sia "Pi-hole in parallelo a un router con API". |
| D9 | Cambiare il provider `dhcp` riporta automaticamente `sync_mode` a `dry-run`. | Evita che il nuovo provider applichi un diff calcolato su uno stato che non conosce. |
| D10 | Un provider si aggiunge creando **una cartella** in `backend/app/providers/<kind>/` (scoperta automatica) e una in `frontend/providers/<kind>/` (una riga nel registro). | Requisito 4 esplicito. |

## Mappa dei sotto-piani

| File | Flusso | Dipende da |
|---|---|---|
| `2026-10-03-01-foundation.md` | F — Fondazione (incluso F5: card Network con solo Save) | — |
| `2026-10-03-02-integrations-auth.md` (parte A) | A — Gotify/e-mail opzionali e configurabili | F |
| `2026-10-03-02-integrations-auth.md` (parte B) | B — better-auth | F |
| `2026-10-03-03-network-providers.md` (parte C) | C — Astrazione provider + Pi-hole come plugin | F |
| `2026-10-03-03-network-providers.md` (parte D) | D — Provider UniFi | C |
| `2026-10-03-04-guests.md` | E — Ospiti | C (e F) |

## Ondate e agenti

```
Ondata 0  ─ F  Fondazione (5 task) ─────────────────────┐ (1 implementer, sequenziale, su branch feat/foundation)
                                                         ▼ merge in main
Ondata 1  ─ A  Integrazioni  ─┐
          ─ B  better-auth    ├─ in parallelo, 3 worktree: feat/integrations, feat/auth, feat/providers
          ─ C  Provider       ─┘
                                merge in ordine A → B → C (C ribasa per ultimo: è il più ampio)
Ondata 2  ─ D  UniFi          ─┐ in parallelo, 2 worktree: feat/unifi, feat/guests (entrambi da main dopo C)
          ─ E  Ospiti         ─┘ merge E → D
Ondata 3  ─ Z  Integrazione: docs, compose/.env.example, review dell'intero branch, prova end-to-end sullo stack reale
```

Ogni flusso si esegue con `superpowers:subagent-driven-development`: per ogni task, un implementer nuovo e poi un reviewer nuovo. Il coordinatore (sessione principale) apre i worktree (`superpowers:using-git-worktrees`), lancia i flussi della stessa ondata in parallelo (`superpowers:dispatching-parallel-agents`) e fa i merge.

Agenti stimati: F 5 task, A 4, B 6, C 7, D 4, E 6, Z 3, cioè 35 task. Ognuno ha un implementer e un reviewer, più un reviewer finale per ogni ondata.

## Proprietà dei file (per evitare conflitti)

Un file appartiene a **un solo** flusso per ondata. Gli altri flussi lo toccano solo nei "registri", con una riga ciascuno.

| Area | Proprietario | Registri condivisi (aggiunta di una riga) |
|---|---|---|
| `backend/app/settingsstore.py`, `backend/app/secretbox.py`, `backend/app/features.py`, `backend/app/api/features.py`, `backend/app/api/internal.py` | F | `features.py` → `FEATURE_PROVIDERS` (A, C, E aggiungono una funzione) |
| `frontend/lib/features.tsx`, `frontend/lib/nav.ts`, `frontend/app/(app)/settings/sections/*` | F | `lib/nav.ts` → `NAV` (E aggiunge "Guests"); `settings/sections/index.ts` → `SECTIONS` (A, B, C, E aggiungono una voce) |
| `backend/app/notify/*`, `backend/app/api/notifications.py`, `frontend/app/(app)/notifications/*` | A | — |
| `frontend/auth*`, `frontend/lib/auth/*`, `frontend/proxy.ts`, `frontend/app/login/*`, `frontend/app/setup/*`, `frontend/app/api/auth/*`, `backend/app/api/authconfig.py` | B | — |
| `backend/app/providers/**`, `backend/app/enforcement/**`, `backend/app/pihole/**` (eliminato), `backend/app/cutover.py` (spostato), `backend/app/api/sync.py`, `backend/app/api/intel.py`, `backend/app/api/providers.py`, `frontend/providers/**`, `frontend/app/(app)/integrations/**`, `frontend/components/sidebar.tsx` | C (poi D solo in `providers/unifi/**`) | `providers/` è scoperto automaticamente |
| `backend/app/guests.py`, `backend/app/api/guests.py`, `frontend/app/(app)/guests/**` | E | — |
| `backend/app/main.py` | — | ogni flusso aggiunge una riga `include_router` |
| `backend/app/config.py` | — | ogni flusso aggiunge i propri campi in un blocco commentato col nome del flusso |
| `frontend/lib/types.ts` | — | ogni flusso aggiunge i propri tipi in fondo, in un blocco con commento `// --- <flusso> ---` |
| Migrazioni Alembic | C: `0008_provider_settings.py` (down `0007`); E: `0009_guests.py` (down `0008`) | numeri **pre-assegnati**; A, B, D non creano migrazioni |
| `docs/**`, `README.md`, `docker-compose.yml`, `.env.example` | Z | ogni flusso scrive le note per Z in `docs/superpowers/handoff/<flusso>.md` (variabili nuove, comportamento cambiato) |

## Convenzioni comuni (valgono per ogni task)

- Comandi di test backend: `scripts/test.sh` (dalla root; usa Postgres locale `janus_test`). Singolo file: `scripts/test.sh tests/test_x.py -v`. Lint: `cd backend && uv run --no-project --with ruff ruff check app tests`.
- Comandi di test frontend: `cd frontend && npm test` (singolo file: `npx vitest run path/to/file.test.ts`); typecheck: `npx tsc --noEmit`; build: `npm run build`.
- Stile: seguire il codice vicino (dataclass frozen, `Protocol` per le cuciture, funzioni `*_once(session_factory)` per i job del worker, `record_event` per gli eventi, componenti da `components/ui.tsx`).
- Mai MAC reali nei test: usare il range documentale `00:00:5E:00:53:xx` (`test_repo_hygiene.py` fallisce altrimenti).
- Messaggi di commit: Conventional Commits (`feat(scope): …`, `refactor(scope): …`), con la riga `Co-Authored-By` richiesta dalla sessione.
- Nessun task cambia `docs/` direttamente: le note vanno nel file di handoff del flusso.

## Review Focus (globale; ogni voce ha un test nel task indicato)

1. **Aggiornamento di un'installazione esistente** con le sole variabili di oggi (Pi-hole, Authentik, Gotify, SMTP). Deve comportarsi in modo identico: Pi-hole come `dhcp` e `dns`, Authentik come pulsante OIDC, e soprattutto `pihole.written_macs` preservato. Se Janus lo perdesse, scambierebbe righe scritte a mano per righe sue. → test in C4 (`test_migration_0008_preserves_written_macs`) e B3 (`authentik env preconfigures oidc provider`).
2. **Installazione nuova senza variabili opzionali.** Avvio senza errori, `/setup` crea l'admin, nessuna voce "Notifications" nel menu, nessun provider: il job `reconcile` non fa nulla e non genera `infra.down`. → test in F3, A3, C5 (`test_reconcile_without_dhcp_provider_is_noop`).
3. **Cambio di provider DHCP mentre si è in `apply`.** Non deve cancellare righe in massa sul nuovo provider; `sync_mode` torna a `dry-run` (D9); `written_macs` è separato per provider. → test in C4 (`test_switching_dhcp_provider_forces_dry_run`).
4. **Segreti.** Mai restituiti dalle API pubbliche; la rotta `/api/internal/*` non è raggiungibile dal browser tramite il proxy Next. → test in F2, F4 (`proxy refuses internal paths`).
5. **Lockout e confini temporali.** L'ultimo amministratore non può cancellarsi; un OIDC configurato male non blocca il login con password. Una scadenza ospite nel passato viene rifiutata; una data senza ora va interpretata nel fuso di Janus (`general.timezone`). → test in B5 e E2.

## Ondata 3 — Integrazione (flusso Z)

### Task Z1: Documentazione e deploy

**Files:** `docs/configuration.md`, `docs/architecture.md`, `docs/operations.md`, `README.md`, `docker-compose.yml`, `.env.example`, `docs/providers/adding-a-provider.md` (lo crea C7; qui va solo collegato).

- [ ] Leggere tutti i `docs/superpowers/handoff/*.md`.
- [ ] `.env.example`: dividere le variabili in "Obbligatorie" (`DB_JANUS_PASSWORD`, `JANUS_INTERNAL_TOKEN`, `AUTH_SECRET`, `JANUS_HOST`) e "Opzionali" (tutte le altre, ognuna con una riga di commento che dice quale sezione accende).
- [ ] `docker-compose.yml`: le variabili opzionali passano come `${VAR:-}` così mancano senza errori; aggiungere `JANUS_SECRET_KEY`, `JANUS_ADMIN_USERNAME`, `JANUS_ADMIN_PASSWORD`, `JANUS_DHCP_PROVIDER`, `JANUS_DNS_PROVIDER`; togliere le variabili `AUTH_AUTHENTIK_*` dal blocco obbligatorio.
- [ ] `docs/configuration.md`: tabella env aggiornata e nuova sezione "Settings editable from the web app" con Integrations, Sign-in & users, Network providers, Guests.
- [ ] `docs/architecture.md`: sostituire "Pi-hole integration" con "Network providers" (ruoli, capability, Pi-hole e UniFi) e aggiornare "Request path" per better-auth.
- [ ] Rigenerare `docs/diagrams/architecture.html` con la skill `archify` partendo dal JSON aggiornato.
- [ ] Commit: `docs: optional integrations, better-auth, guests and network providers`.

### Task Z2: Review dell'intero branch

- [ ] Lanciare `superpowers:requesting-code-review` sull'intervallo `main@{prima di F}..HEAD`, chiedendo al reviewer di verificare in particolare le 5 voci del Review Focus.
- [ ] Applicare i fix con `superpowers:receiving-code-review`.

### Task Z3: Prova end-to-end sullo stack reale (manuale, con l'utente)

- [ ] `docker compose up -d --build` con l'`.env` di produzione attuale, senza modifiche. Verificare: login Authentik, menu identico, `GET /api/sync/plan` restituisce il diff vuoto (nessuna differenza rispetto a prima), arriva una notifica di test via Gotify ed e-mail.
- [ ] Copia dello stack con un `.env` minimo (solo le variabili obbligatorie): `/setup`, login con password, niente Notifications/Guests nel menu, Settings mostra le sezioni di configurazione.
- [ ] Dalla UI aggiungere un ospite di test (MAC documentale) con scadenza fra 2 minuti; verificare che sparisca e che compaia l'evento `guest.expired`.
- [ ] Per UniFi: checklist D4, da eseguire con l'amico sul suo hardware.
