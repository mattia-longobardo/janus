import { BACKEND_URL, backendHeaders } from "@/lib/backend";

export type AuthProvider = {
  id: string;
  name: string;
  discovery_url: string;
  client_id: string;
  client_secret: string;
  scopes: string[];
};

export type AuthConfig = { allowed_emails: string[]; providers: AuthProvider[]; version: string };

const TTL_MS = 15_000;
const TIMEOUT_MS = 3_000;
const OFFLINE: AuthConfig = { allowed_emails: [], providers: [], version: "offline" };

let lastGood: AuthConfig | null = null;
let cached: { at: number; config: AuthConfig } | null = null;
let inflight: Promise<AuthConfig> | null = null;
let failing = false;

function isAuthConfig(value: unknown): value is AuthConfig {
  const v = value as Partial<AuthConfig> | null;
  return Boolean(v) && Array.isArray(v!.allowed_emails) && Array.isArray(v!.providers) && typeof v!.version === "string";
}

async function load(): Promise<AuthConfig> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/internal/auth-config`, {
      headers: backendHeaders(),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body: unknown = await response.json();
    if (!isAuthConfig(body)) throw new Error("unexpected response");
    lastGood = body;
    if (failing) console.info("auth-config: backend reachable again");
    failing = false;
    return body;
  } catch (err) {
    // The login form must keep working while the backend is down: serve the
    // last good config, or one with no OIDC providers and an empty allowlist.
    if (!failing) {
      const reason = err instanceof Error ? err.message : "request failed";
      console.warn(`auth-config: ${reason}; using the ${lastGood ? "last good" : "offline"} sign-in configuration`);
    }
    failing = true;
    return lastGood ?? OFFLINE;
  }
}

/** Sign-in configuration from the backend, cached in memory for 15 s. */
export async function fetchAuthConfig(): Promise<AuthConfig> {
  if (cached && Date.now() - cached.at < TTL_MS) return cached.config;
  inflight ??= load().then((config) => {
    cached = { at: Date.now(), config };
    inflight = null;
    return config;
  });
  return inflight;
}

/** Connection string for the better-auth tables; defaults to the backend database. */
export function authDatabaseUrl(): string | undefined {
  return process.env.AUTH_DATABASE_URL || process.env.JANUS_DATABASE_URL?.replace(/^postgresql\+\w+:/, "postgresql:");
}
