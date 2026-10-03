import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { LoginForm } from "@/app/login/login-form";
import { fetchAuthConfig } from "@/lib/auth/config";
import { getHasUsers } from "@/lib/auth/server";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ callbackUrl?: string; error?: string }> }) {
  const { callbackUrl, error } = await searchParams;
  if (!(await getHasUsers())) redirect("/setup");
  // Offline, fetchAuthConfig yields no providers: the password form always works.
  const providers = (await fetchAuthConfig()).providers.map(({ id, name }) => ({ id, name }));

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
        <p className="text-sm text-muted">Home network control. Sign in to continue.</p>
        <LoginForm providers={providers} error={error} callbackUrl={callbackUrl} />
      </div>
    </main>
  );
}
