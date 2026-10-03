export const DISCOVERY_TIMEOUT_MS = 3_000;

/**
 * Checks an OIDC discovery document within `timeoutMs`. Returns null when it is
 * usable, otherwise a short reason (never the response body).
 */
export async function probeDiscovery(url: string, timeoutMs: number = DISCOVERY_TIMEOUT_MS): Promise<string | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  // The race guards against a fetch that ignores the abort signal.
  const timeout = new Promise<string>((resolve) => {
    timer = setTimeout(() => resolve(`no answer within ${timeoutMs} ms`), timeoutMs);
  });
  const check = (async () => {
    try {
      const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
      if (!response.ok) return `HTTP ${response.status}`;
      const doc = (await response.json()) as { authorization_endpoint?: unknown; token_endpoint?: unknown } | null;
      if (typeof doc?.authorization_endpoint !== "string" || typeof doc?.token_endpoint !== "string") {
        return "discovery document has no authorization or token endpoint";
      }
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : "request failed";
    }
  })();
  try {
    return await Promise.race([check, timeout]);
  } finally {
    clearTimeout(timer);
  }
}
