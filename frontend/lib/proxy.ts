import { backendHeaders } from "@/lib/backend";

const WRITES = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const MAX_BODY = 1_000_000;

export function isCrossSite(req: Request, allowedOrigins: string[]): boolean {
  if (!WRITES.has(req.method)) return false;
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") return true;
  const origin = req.headers.get("origin");
  return Boolean(origin) && !allowedOrigins.includes(String(origin));
}

interface ForwardOptions {
  signedIn: boolean;
  backend: string;
  allowedOrigins: string[];
  fetcher?: typeof fetch;
}

export async function forward(req: Request, path: string[], options: ForwardOptions): Promise<Response> {
  if (!options.signedIn) return Response.json({ detail: "not signed in" }, { status: 401 });
  const first = decodeURIComponent(path[0] ?? "").split("/")[0].toLowerCase();
  if (first === "internal") return Response.json({ detail: "not found" }, { status: 404 });
  if (isCrossSite(req, options.allowedOrigins)) {
    return Response.json({ detail: "cross-site request refused" }, { status: 403 });
  }
  const url = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, options.backend);
  url.search = new URL(req.url).search;
  let body: ArrayBuffer | undefined;
  if (WRITES.has(req.method)) {
    body = await req.arrayBuffer();
    if (body.byteLength > MAX_BODY) return Response.json({ detail: "request too large" }, { status: 413 });
  }
  const upstream = await (options.fetcher ?? fetch)(url, {
    method: req.method,
    headers: backendHeaders(req.headers),
    body,
    redirect: "manual",
    cache: "no-store",
  });
  const headers = new Headers();
  for (const name of ["content-type", "cache-control", "content-disposition"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
