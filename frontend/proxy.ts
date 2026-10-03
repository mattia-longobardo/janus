import { NextResponse, type NextRequest } from "next/server";

import { getAllowedSession } from "@/lib/auth/server";

export async function proxy(req: NextRequest) {
  if (await getAllowedSession(req.headers)) return NextResponse.next();
  if (req.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: "not signed in" }, { status: 401 });
  }
  const login = new URL("/login", req.nextUrl.origin);
  login.searchParams.set("callbackUrl", `${req.nextUrl.pathname}${req.nextUrl.search}`);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!api/auth(?:/|$)|api/healthz$|login$|_next/static/|_next/image(?:/|$)|favicon\\.ico$|icon\\.svg$|robots\\.txt$).*)"],
};
