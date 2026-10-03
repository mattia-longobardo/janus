import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const { fetchAuthConfig, social } = vi.hoisted(() => ({ fetchAuthConfig: vi.fn(), social: vi.fn() }));
vi.mock("@/lib/auth/config", () => ({ fetchAuthConfig }));
vi.mock("@/lib/auth/client", () => ({ authClient: { signIn: { social, username: vi.fn() } } }));
vi.mock("@/app/setup/actions", () => ({ createFirstAdmin: vi.fn() }));

import SetupPage from "./page";

const provider = { id: "authentik", name: "Authentik", discovery_url: "", client_id: "", client_secret: "", scopes: [] };

beforeEach(() => vi.clearAllMocks());

it("offers the configured OIDC providers next to the local-admin form", async () => {
  fetchAuthConfig.mockResolvedValue({ allowed_emails: [], providers: [provider], version: "v1" });
  social.mockResolvedValue({ error: null });
  render(await SetupPage());
  expect(screen.getByRole("button", { name: "Create administrator" })).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Sign in with Authentik" }));
  expect(social).toHaveBeenCalledWith({ provider: "authentik", callbackURL: "/" });
});

it("shows only the local-admin form without providers", async () => {
  fetchAuthConfig.mockResolvedValue({ allowed_emails: [], providers: [], version: "v1" });
  render(await SetupPage());
  expect(screen.getByRole("button", { name: "Create administrator" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Sign in with/ })).toBeNull();
});

it("reports an unreachable provider", async () => {
  fetchAuthConfig.mockResolvedValue({ allowed_emails: [], providers: [provider], version: "v1" });
  social.mockResolvedValue({ error: { code: "PROVIDER_NOT_FOUND", message: "x" } });
  render(await SetupPage());
  await userEvent.click(screen.getByRole("button", { name: "Sign in with Authentik" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Authentik is not reachable");
});
