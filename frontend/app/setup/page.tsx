import type { Metadata } from "next";

import { SetupForm } from "@/app/setup/setup-form";

export const metadata: Metadata = { title: "Set up Janus" };

export default function SetupPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <div className="flex w-full max-w-sm flex-col gap-6 rounded-2xl border border-line bg-card p-8">
        <h1 className="font-display text-3xl font-bold tracking-tight">Janus</h1>
        <p className="text-sm text-muted">Create the first administrator. Password: at least 12 characters.</p>
        <SetupForm />
      </div>
    </main>
  );
}
