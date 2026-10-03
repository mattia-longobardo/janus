import "server-only";

import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { admin, genericOAuth, username } from "better-auth/plugins";
import { Pool } from "pg";

import { authDatabaseUrl, fetchAuthConfig, type AuthConfig, type AuthProvider } from "@/lib/auth/config";
import { probeDiscovery } from "@/lib/auth/discovery";
import { isUserAllowed } from "@/lib/auth/gate";

// Keep the schema-affecting options (additional fields, username/admin
// plugins) in sync with scripts/migrate-auth.mjs, which creates the tables.
const pool = new Pool({ connectionString: authDatabaseUrl(), options: "-c search_path=auth" });

const RETRY_MS = 15_000;

function build(cfg: AuthConfig, providers: AuthProvider[]) {
  return betterAuth({
    database: pool,
    secret: process.env.AUTH_SECRET,
    baseURL: process.env.AUTH_URL,
    session: { expiresIn: 12 * 60 * 60, updateAge: 60 * 60 },
    emailAndPassword: { enabled: true, disableSignUp: true },
    // An IdP account must never be attached to an existing (e.g. local) user.
    account: { accountLinking: { enabled: false } },
    user: { additionalFields: { source: { type: "string", defaultValue: "oidc", input: false } } },
    databaseHooks: {
      user: {
        create: {
          before: async (user) => {
            // OIDC sign-ins create a user only when the e-mail is allowlisted.
            if (user.source !== "local" && !isUserAllowed(user, cfg.allowed_emails)) return false;
            return { data: user };
          },
        },
      },
    },
    plugins: [
      username(),
      admin({ defaultRole: "user" }),
      genericOAuth({
        config: providers.map((p) => ({
          providerId: p.id,
          name: p.name,
          discoveryUrl: p.discovery_url,
          clientId: p.client_id,
          clientSecret: p.client_secret,
          scopes: p.scopes,
        })),
      }),
      nextCookies(),
    ],
  });
}

export type Auth = ReturnType<typeof build>;
export type Session = NonNullable<Awaited<ReturnType<Auth["api"]["getSession"]>>>;

// Providers whose discovery did not answer, per config version. better-auth
// fetches discovery without a timeout while it initialises, so a hanging IdP
// would stall every auth request (password sign-in included): such providers
// are left out and re-probed in the background every RETRY_MS.
type Probe = { version: string; failed: Set<string>; checkedAt: number; retrying: boolean };
let probe: Probe | null = null;
let cached: { key: string; auth: Auth } | null = null;

async function probeProviders(providers: AuthProvider[], known: Set<string>): Promise<Set<string>> {
  const results = await Promise.all(providers.map(async (p) => [p, await probeDiscovery(p.discovery_url)] as const));
  const failed = new Set<string>();
  for (const [p, reason] of results) {
    if (reason === null) {
      if (known.has(p.id)) console.info(`auth: OIDC provider "${p.id}" is reachable again`);
      continue;
    }
    failed.add(p.id);
    if (!known.has(p.id)) console.warn(`auth: OIDC provider "${p.id}" left out, discovery failed: ${reason}`);
  }
  return failed;
}

async function failedProviders(cfg: AuthConfig): Promise<Set<string>> {
  if (!probe || probe.version !== cfg.version) {
    const failed = await probeProviders(cfg.providers, new Set());
    probe = { version: cfg.version, failed, checkedAt: Date.now(), retrying: false };
  } else if (probe.failed.size && !probe.retrying && Date.now() - probe.checkedAt >= RETRY_MS) {
    const current = probe;
    current.retrying = true;
    void probeProviders(cfg.providers.filter((p) => current.failed.has(p.id)), current.failed).then((failed) => {
      if (probe === current) probe = { version: current.version, failed, checkedAt: Date.now(), retrying: false };
    });
  }
  return probe.failed;
}

/** The better-auth instance for the current sign-in configuration and reachable providers. */
export async function getAuth(): Promise<Auth> {
  const cfg = await fetchAuthConfig();
  const failed = await failedProviders(cfg);
  const key = `${cfg.version}|${[...failed].sort().join(",")}`;
  if (!cached || cached.key !== key) {
    cached = { key, auth: build(cfg, cfg.providers.filter((p) => !failed.has(p.id))) };
  }
  return cached.auth;
}

export async function getSession(headers: Headers): Promise<Session | null> {
  const auth = await getAuth();
  return auth.api.getSession({ headers });
}

/** The session, but only while its user may still use Janus (allowlist re-checked on every call). */
export async function getAllowedSession(headers: Headers): Promise<Session | null> {
  const [session, cfg] = await Promise.all([getSession(headers), fetchAuthConfig()]);
  if (!session) return null;
  return isUserAllowed(session.user, cfg.allowed_emails) ? session : null;
}

const HAS_USERS_TTL_MS = 10_000;
let hasUsersSince: number | null = null;

/** Whether any user exists yet; once true it is cached for 10 s (it can only turn true -> false by wiping the DB). */
export async function getHasUsers(): Promise<boolean> {
  if (hasUsersSince !== null && Date.now() - hasUsersSince < HAS_USERS_TTL_MS) return true;
  const { rows } = await pool.query<{ exists: boolean }>('SELECT EXISTS (SELECT 1 FROM auth."user") AS "exists"');
  const exists = rows[0]?.exists === true;
  hasUsersSince = exists ? Date.now() : null;
  return exists;
}
