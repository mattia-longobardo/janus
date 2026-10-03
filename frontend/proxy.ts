import { NextResponse, type NextRequest } from "next/server";

import { getAllowedSession, getHasUsers } from "@/lib/auth/server";
import { decide } from "@/lib/auth/session-guard";

export async function proxy(req: NextRequest) {
  const path = `${req.nextUrl.pathname}${req.nextUrl.search}`;
  const result = decide(path, Boolean(await getAllowedSession(req.headers)), await getHasUsers());
  if (result.kind === "next") return NextResponse.next();
  if (result.kind === "json401") return NextResponse.json({ detail: "not signed in" }, { status: 401 });
  return NextResponse.redirect(new URL(result.to, req.nextUrl.origin));
}

export const config = {
  matcher: ["/((?!api/auth(?:/|$)|api/healthz$|login$|_next/static/|_next/image(?:/|$)|favicon\\.ico$|icon\\.svg$|robots\\.txt$).*)"],
};
