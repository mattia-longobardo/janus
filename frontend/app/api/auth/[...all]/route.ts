import { toNextJsHandler } from "better-auth/next-js";

import { getAuth } from "@/lib/auth/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function handle(req: Request): Promise<Response> {
  const { GET, POST } = toNextJsHandler(await getAuth());
  return req.method === "POST" ? POST(req) : GET(req);
}

export { handle as GET, handle as POST };
