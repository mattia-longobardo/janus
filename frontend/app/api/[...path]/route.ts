import { getAllowedSession } from "@/lib/auth/server";
import { BACKEND_URL } from "@/lib/backend";
import { forward } from "@/lib/proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function handle(req: Request, context: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const session = await getAllowedSession(req.headers);
  const { path } = await context.params;
  const allowedOrigins = [new URL(req.url).origin, process.env.AUTH_URL].filter((value): value is string => Boolean(value));
  return forward(req, path, { signedIn: Boolean(session), backend: BACKEND_URL, allowedOrigins });
}

export { handle as DELETE, handle as GET, handle as PATCH, handle as POST, handle as PUT };
