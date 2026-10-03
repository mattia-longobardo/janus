"use client";

import { useState, type FormEvent } from "react";

import { safeCallbackUrl } from "@/lib/auth/callback-url";
import { authClient } from "@/lib/auth/client";

export type LoginProvider = { id: string; name: string };

const inputClass = "h-11 w-full rounded-lg border border-line bg-card px-3 text-sm";
const primaryClass = "h-12 w-full rounded-lg border border-accent bg-accent text-sm font-semibold text-accent-ink disabled:opacity-60";

export function urlErrorMessage(error: string | undefined): string | null {
  if (!error) return null;
  return error === "AccessDenied" ? "This account is not allowed to use Janus." : "Sign-in is not available right now. Try again.";
}

export function LoginForm({ providers, error, callbackUrl }: { providers: LoginProvider[]; error?: string; callbackUrl?: string }) {
  const target = safeCallbackUrl(callbackUrl);
  const [message, setMessage] = useState<string | null>(urlErrorMessage(error));
  const [busy, setBusy] = useState(false);

  async function onPassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setMessage(null);
    try {
      const { error: err } = await authClient.signIn.username({
        username: String(form.get("username") ?? ""),
        password: String(form.get("password") ?? ""),
      });
      if (err) {
        setMessage(err.message || "Sign-in failed.");
        return;
      }
      window.location.assign(target);
    } catch {
      setMessage("Sign-in is not available right now. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function onProvider(provider: LoginProvider) {
    setBusy(true);
    setMessage(null);
    try {
      const { error: err } = await authClient.signIn.social({ provider: provider.id, callbackURL: target });
      if (err) setMessage(err.code === "PROVIDER_NOT_FOUND" ? `${provider.name} is not reachable right now. Try again later.` : err.message || "Sign-in failed.");
    } catch {
      setMessage(`${provider.name} is not reachable right now. Try again later.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {message && (
        <p role="alert" className="rounded-lg border border-bad px-3 py-2 text-sm text-bad">
          {message}
        </p>
      )}
      <form onSubmit={onPassword} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm text-muted">
          Username
          <input name="username" autoComplete="username" required className={inputClass} />
        </label>
        <label className="flex flex-col gap-1 text-sm text-muted">
          Password
          <input name="password" type="password" autoComplete="current-password" required className={inputClass} />
        </label>
        <button type="submit" disabled={busy} className={primaryClass}>
          Sign in
        </button>
      </form>
      {providers.map((p) => (
        <button
          key={p.id}
          type="button"
          disabled={busy}
          onClick={() => onProvider(p)}
          className="h-12 w-full rounded-lg border border-line bg-card text-sm font-semibold disabled:opacity-60"
        >
          Sign in with {p.name}
        </button>
      ))}
    </div>
  );
}
