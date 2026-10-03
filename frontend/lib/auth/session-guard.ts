export type Decision = { kind: "next" } | { kind: "json401" } | { kind: "redirect"; to: string };

/** What the proxy does with a request: `path` may carry a query string. */
export function decide(path: string, signedIn: boolean, hasUsers: boolean): Decision {
  const pathname = path.split("?")[0];
  const isSetup = pathname === "/setup";
  if (!hasUsers) return isSetup ? { kind: "next" } : { kind: "redirect", to: "/setup" };
  if (isSetup) return { kind: "redirect", to: "/login" };
  if (signedIn) return { kind: "next" };
  if (pathname.startsWith("/api/")) return { kind: "json401" };
  return { kind: "redirect", to: `/login?callbackUrl=${encodeURIComponent(path)}` };
}
