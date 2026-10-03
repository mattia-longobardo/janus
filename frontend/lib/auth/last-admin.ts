type Account = { id: string; role?: string | null };

// The last admin can be neither deleted nor demoted.
export function canRemoveOrDemote(target: Account, users: Account[]): boolean {
  if (target.role !== "admin") return true;
  return users.some((u) => u.id !== target.id && u.role === "admin");
}
