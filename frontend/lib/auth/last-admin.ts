type Account = { id: string; role?: string | null };

export const LAST_ADMIN_MESSAGE = "cannot remove the last admin";

// better-auth stores multiple roles as a comma-separated string.
function hasAdmin(role: unknown): boolean {
  const roles = Array.isArray(role) ? role : typeof role === "string" ? role.split(",") : [];
  return roles.some((r) => typeof r === "string" && r.trim() === "admin");
}

// The last admin can be neither deleted nor demoted.
export function canRemoveOrDemote(target: Account, users: Account[]): boolean {
  if (!hasAdmin(target.role)) return true;
  return users.some((u) => u.id !== target.id && hasAdmin(u.role));
}

/** The user an admin-plugin request would delete, ban or strip of the admin role, if any. */
export function adminLossTarget(path: string, body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const { userId, role, data } = body as { userId?: unknown; role?: unknown; data?: unknown };
  if (typeof userId !== "string") return null;
  switch (path) {
    case "/admin/remove-user":
    case "/admin/ban-user":
      return userId;
    case "/admin/set-role":
      return hasAdmin(role) ? null : userId;
    case "/admin/update-user": {
      if (typeof data !== "object" || data === null) return null;
      const update = data as { role?: unknown; banned?: unknown };
      const demotes = "role" in update && !hasAdmin(update.role);
      return demotes || update.banned === true ? userId : null;
    }
    default:
      return null;
  }
}
