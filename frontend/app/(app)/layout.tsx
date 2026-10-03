import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { Shell } from "@/components/shell";
import { getAllowedSession } from "@/lib/auth/server";

export default async function AppLayout({ children }: { children: ReactNode }) {
  const session = await getAllowedSession(await headers());
  if (!session) redirect("/login?error=AccessDenied");
  const { user } = session;
  const currentUser = { id: user.id, name: user.username ?? user.name ?? user.email, role: user.role ?? null, source: user.source ?? null };
  return <Shell user={currentUser}>{children}</Shell>;
}
