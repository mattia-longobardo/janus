"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { getAuth, getHasUsers } from "@/lib/auth/server";

export type SetupState = { error: string | null };

const MIN_PASSWORD = 12;
const USERNAME_RE = /^[a-z0-9_.]{3,30}$/;

export async function createFirstAdmin(_prev: SetupState, formData: FormData): Promise<SetupState> {
  if (await getHasUsers()) redirect("/login");

  const username = String(formData.get("username") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");
  const confirm = String(formData.get("confirm") ?? "");
  if (!USERNAME_RE.test(username)) return { error: "Username must be 3-30 characters: letters, digits, underscore or dot." };
  if (password.length < MIN_PASSWORD) return { error: `Password must be at least ${MIN_PASSWORD} characters.` };
  if (password !== confirm) return { error: "The passwords do not match." };

  const auth = await getAuth();
  try {
    await auth.api.createUser({
      body: {
        email: `${username}@local.invalid`,
        password,
        name: username,
        role: "admin",
        data: { username, displayUsername: username, source: "local" },
      },
    });
    await auth.api.signInUsername({ body: { username, password }, headers: await headers() });
  } catch (e) {
    // Never hand better-auth or database internals to an unauthenticated visitor; the log keeps the detail.
    console.error("setup: creating the first admin failed", e);
    return { error: "Could not create the administrator. Check the server log and try again." };
  }
  redirect("/");
}
