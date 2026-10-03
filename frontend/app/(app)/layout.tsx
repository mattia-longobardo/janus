import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { Shell } from "@/components/shell";
import { getAllowedSession } from "@/lib/auth/server";

export default async function AppLayout({ children }: { children: ReactNode }) {
  const session = await getAllowedSession(await headers());
  if (!session) redirect("/login?error=AccessDenied");
  return <Shell user={session.user.name ?? session.user.email ?? "signed in"}>{children}</Shell>;
}
