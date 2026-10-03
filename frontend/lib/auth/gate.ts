export type GateUser = { email?: string | null; source?: string | null; banned?: boolean | null };

// Local accounts are managed in Janus itself; everyone else (OIDC, or a user
// with no recorded source) must be on the allowlist at every request.
export function isUserAllowed(user: GateUser, allowedEmails: string[]): boolean {
  if (user.banned) return false;
  if (user.source === "local") return true;
  const email = user.email?.trim().toLowerCase();
  if (!email) return false;
  return allowedEmails.some((entry) => entry.trim().toLowerCase() === email);
}

/**
 * What to store when better-auth creates a user, or false to refuse it. OIDC users must be allowlisted; the very
 * first one becomes admin, so an install upgraded from Authentik-only sign-in is not left without an administrator.
 */
export function newUserData<T extends GateUser & { role?: string | null }>(
  user: T,
  allowedEmails: string[],
  noUsersYet: boolean,
): false | { data: T } {
  if (user.source === "local") return { data: user };
  if (!isUserAllowed(user, allowedEmails)) return false;
  return { data: noUsersYet ? { ...user, role: "admin" } : user };
}
