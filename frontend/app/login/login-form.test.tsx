import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const signIn = vi.hoisted(() => ({ username: vi.fn(), social: vi.fn() }));
vi.mock("@/lib/auth/client", () => ({ authClient: { signIn } }));

import { LoginForm } from "./login-form";

async function submitCredentials(password = "correct horse battery") {
  await userEvent.type(screen.getByLabelText("Username"), "admin");
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginForm", () => {
  it("always offers username and password even with no providers", async () => {
    signIn.username.mockResolvedValue({ error: null });
    render(<LoginForm providers={[]} />);
    await submitCredentials();
    expect(signIn.username).toHaveBeenCalledWith(expect.objectContaining({ username: "admin", password: "correct horse battery" }));
    expect(screen.queryByRole("button", { name: /Sign in with/ })).toBeNull();
  });

  it("renders one button per configured OIDC provider", async () => {
    signIn.social.mockResolvedValue({ error: null });
    render(<LoginForm providers={[{ id: "authentik", name: "Authentik" }, { id: "kc", name: "Keycloak" }]} callbackUrl="/groups" />);
    expect(screen.getByRole("button", { name: "Sign in with Authentik" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Sign in with Keycloak" }));
    expect(signIn.social).toHaveBeenCalledWith({ provider: "kc", callbackURL: "/groups" });
  });

  it("sanitizes an unsafe callback URL", async () => {
    signIn.social.mockResolvedValue({ error: null });
    render(<LoginForm providers={[{ id: "kc", name: "Keycloak" }]} callbackUrl="//evil.example" />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in with Keycloak" }));
    expect(signIn.social).toHaveBeenCalledWith({ provider: "kc", callbackURL: "/" });
  });

  it("shows a readable message on wrong credentials", async () => {
    signIn.username.mockResolvedValueOnce({ error: { message: "Invalid username or password" } });
    render(<LoginForm providers={[]} />);
    await submitCredentials("nope");
    expect((await screen.findByRole("alert")).textContent).toContain("Invalid username or password");
  });

  it("shows a readable message when a provider is unavailable", async () => {
    signIn.social.mockResolvedValueOnce({ error: { code: "PROVIDER_NOT_FOUND", message: "Provider not found" } });
    render(<LoginForm providers={[{ id: "kc", name: "Keycloak" }]} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in with Keycloak" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Keycloak is not reachable right now");
  });

  it("shows the error passed in from the URL", () => {
    render(<LoginForm providers={[]} error="AccessDenied" />);
    expect(screen.getByRole("alert").textContent).toContain("not allowed");
  });
});
