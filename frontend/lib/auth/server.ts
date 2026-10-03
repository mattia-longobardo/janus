import "server-only";

import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { admin, genericOAuth, username } from "better-auth/plugins";
import { Pool } from "pg";

import { authDatabaseUrl, fetchAuthConfig, type AuthConfig } from "@/lib/auth/config";
import { isUserAllowed } from "@/lib/auth/gate";

// Keep the schema-affecting options (additional fields, username/admin
// plugins) in sync with scripts/migrate-auth.mjs, which creates the tables.
const pool = new Pool({ connectionString: authDatabaseUrl(), options: "-c search_path=auth" });

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
        config: cfg.providers.map((p) => ({
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

let cached: { version: string; auth: Auth } | null = null;

/** The better-auth instance for the current sign-in configuration; rebuilt when its version changes. */
export async function getAuth(): Promise<Auth> {
  const cfg = await fetchAuthConfig();
  if (!cached || cached.version !== cfg.version) cached = { version: cfg.version, auth: build(cfg) };
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
