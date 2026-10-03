"use client";

import { useActionState } from "react";

import { createFirstAdmin, type SetupState } from "@/app/setup/actions";
import { Notice } from "@/components/ui";

const inputClass = "h-11 w-full rounded-lg border border-line bg-card px-3 text-sm";

export function SetupForm() {
  const [state, action, pending] = useActionState<SetupState, FormData>(createFirstAdmin, { error: null });
  return (
    <form action={action} className="flex flex-col gap-3">
      {state.error && <Notice tone="error">{state.error}</Notice>}
      <label className="flex flex-col gap-1 text-sm text-muted">
        Username
        <input name="username" autoComplete="username" required className={inputClass} />
      </label>
      <label className="flex flex-col gap-1 text-sm text-muted">
        Password
        <input name="password" type="password" autoComplete="new-password" minLength={12} required className={inputClass} />
      </label>
      <label className="flex flex-col gap-1 text-sm text-muted">
        Confirm password
        <input name="confirm" type="password" autoComplete="new-password" minLength={12} required className={inputClass} />
      </label>
      <button type="submit" disabled={pending} className="h-12 w-full rounded-lg border border-accent bg-accent text-sm font-semibold text-accent-ink disabled:opacity-60">
        Create administrator
      </button>
    </form>
  );
}
