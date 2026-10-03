import type { Metadata } from "next";

import { ProviderButtons } from "@/app/login/login-form";
import { SetupForm } from "@/app/setup/setup-form";
import { fetchAuthConfig } from "@/lib/auth/config";

export const metadata: Metadata = { title: "Set up Janus" };

export default async function SetupPage() {
  // Offline, fetchAuthConfig yields no providers: only the local-admin form is offered.
  const providers = (await fetchAuthConfig()).providers.map(({ id, name }) => ({ id, name }));
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <div className="flex w-full max-w-sm flex-col gap-6 rounded-2xl border border-line bg-card p-8">
        <h1 className="font-display text-3xl font-bold tracking-tight">Janus</h1>
        <p className="text-sm text-muted">Create the first administrator. Password: at least 12 characters.</p>
        <SetupForm />
        {providers.length > 0 && (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted">Or sign in with an allowlisted account: the first one becomes administrator.</p>
            <ProviderButtons providers={providers} callbackUrl="/" />
          </div>
        )}
      </div>
    </main>
  );
}
