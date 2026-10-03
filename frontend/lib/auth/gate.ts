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
