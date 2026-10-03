import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { getAuth } from "@/lib/auth/server";

export const metadata: Metadata = { title: "Sign in" };

function safeTarget(url: string | undefined): string {
  return url && url.startsWith("/") && !url.startsWith("//") ? url : "/";
}

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ callbackUrl?: string; error?: string }> }) {
  const { callbackUrl, error } = await searchParams;
  const target = safeTarget(callbackUrl);

  async function login() {
    "use server";
    // Interim: B4 replaces this page with the password form and per-provider buttons.
    const auth = await getAuth();
    const { url } = await auth.api.signInSocial({ body: { provider: "authentik", callbackURL: target, disableRedirect: true }, headers: await headers() });
    if (url) redirect(url);
  }

  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <div className="flex w-full max-w-sm flex-col gap-6 rounded-2xl border border-line bg-card p-8">
        <div className="flex items-center gap-3">
          <svg width="34" height="34" viewBox="0 0 32 32" fill="none" stroke="var(--accent)" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
            <path d="M13 4a12 12 0 0 0 0 24" />
            <path d="M19 4a12 12 0 0 1 0 24" />
            <path d="M16 9v14" />
          </svg>
          <h1 className="font-display text-3xl font-bold tracking-tight">Janus</h1>
        </div>
        <p className="text-sm text-muted">Home network control. Sign in with your Authentik account.</p>
        {error && (
          <p role="alert" className="rounded-lg border border-bad px-3 py-2 text-sm text-bad">
            {error === "AccessDenied"
              ? "This account is not allowed to use Janus."
              : "Sign-in is not available right now. Check the Authentik application for Janus and try again."}
          </p>
        )}
        <form action={login}>
          <button type="submit" className="h-12 w-full rounded-lg border border-accent bg-accent text-sm font-semibold text-accent-ink">
            Sign in with Authentik
          </button>
        </form>
      </div>
    </main>
  );
}
