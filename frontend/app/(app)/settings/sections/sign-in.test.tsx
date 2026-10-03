import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { authClient } from "@/lib/auth/client";
import * as currentUser from "@/lib/current-user";
import { SignInSection } from "./sign-in";

vi.mock("@/lib/auth/client", () => ({
  authClient: {
    changePassword: vi.fn(),
    admin: { listUsers: vi.fn(), createUser: vi.fn(), removeUser: vi.fn(), setRole: vi.fn(), setUserPassword: vi.fn() },
  },
}));

const SETTINGS = {
  allowed_emails: "a@x.io",
  allowed_emails_source: "env",
  providers: [
    { id: "authentik", name: "Authentik", discovery_url: "https://id/.well-known/openid-configuration", client_id: "cid", client_secret: true, scopes: "openid email", enabled: true, source: "env" },
  ],
};

function mockSession(user: { id: string; role: string; source: string }) {
  vi.spyOn(currentUser, "useCurrentUser").mockReturnValue({ name: user.id, ...user });
}
function mockUsers(users: Record<string, unknown>[]) {
  vi.mocked(authClient.admin.listUsers).mockResolvedValue({ data: { users, total: users.length }, error: null } as never);
}

const USERS = [
  { id: "a", name: "admin", role: "admin", source: "local" },
  { id: "u", name: "kid", role: "user", source: "local" },
];

describe("SignInSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(api, "get").mockResolvedValue(SETTINGS);
  });

  it("disables Delete on the last admin", async () => {
    mockSession({ id: "a", role: "admin", source: "local" });
    mockUsers(USERS);
    render(<SignInSection />);
    expect((await screen.findByRole("button", { name: "Delete admin" })) as HTMLButtonElement).toHaveProperty("disabled", true);
    expect((screen.getByRole("button", { name: "Delete kid" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Make admin user" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("hides users and providers from non-admins but shows change password", async () => {
    mockSession({ id: "u", role: "user", source: "local" });
    render(<SignInSection />);
    expect(await screen.findByText("Change my password")).toBeTruthy();
    expect(screen.queryByText("Users")).toBeNull();
    expect(screen.queryByText("OIDC providers")).toBeNull();
    expect(authClient.admin.listUsers).not.toHaveBeenCalled();
  });

  it("creates a local user with the local.invalid e-mail", async () => {
    mockSession({ id: "a", role: "admin", source: "local" });
    mockUsers(USERS);
    vi.mocked(authClient.admin.createUser).mockResolvedValue({ data: {}, error: null } as never);
    render(<SignInSection />);
    await userEvent.type(await screen.findByLabelText("Username"), "bob");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Add user" }));
    expect(authClient.admin.createUser).toHaveBeenCalledWith({
      email: "bob@local.invalid",
      password: "correct horse battery",
      name: "bob",
      role: "user",
      data: { username: "bob", source: "local" },
    });
  });

  it("saves allowlist and providers with one Save and shows the callback URL", async () => {
    mockSession({ id: "a", role: "admin", source: "local" });
    mockUsers(USERS);
    const put = vi.spyOn(api, "put").mockResolvedValue(SETTINGS);
    render(<SignInSection />);
    const box = await screen.findByLabelText("Allowed e-mails (OIDC)");
    await userEvent.type(box, "{enter}b@x.io");
    expect(screen.getByText(`${location.origin}/api/auth/callback/authentik`)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(put).toHaveBeenCalledWith("/settings/auth", {
      allowed_emails: "a@x.io\nb@x.io",
      providers: [
        { id: "authentik", name: "Authentik", discovery_url: SETTINGS.providers[0].discovery_url, client_id: "cid", scopes: "openid email", enabled: true },
      ],
    });
  });

  it("sends a new provider secret", async () => {
    mockSession({ id: "a", role: "admin", source: "local" });
    mockUsers(USERS);
    const put = vi.spyOn(api, "put").mockResolvedValue(SETTINGS);
    render(<SignInSection />);
    await userEvent.click(await screen.findByRole("button", { name: "Change Client secret" }));
    await userEvent.type(screen.getByLabelText("Client secret"), "s3");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(put.mock.calls[0][1]).toMatchObject({ providers: [{ id: "authentik", client_secret: "s3" }] });
  });

  it("changes my password", async () => {
    mockSession({ id: "u", role: "user", source: "local" });
    vi.mocked(authClient.changePassword).mockResolvedValue({ data: {}, error: null } as never);
    render(<SignInSection />);
    await userEvent.type(await screen.findByLabelText("Current password"), "old-password-1");
    await userEvent.type(screen.getByLabelText("New password"), "new-password-123");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(authClient.changePassword).toHaveBeenCalledWith({ currentPassword: "old-password-1", newPassword: "new-password-123", revokeOtherSessions: true });
  });

  it("asks before deleting a user or changing a role", async () => {
    mockSession({ id: "a", role: "admin", source: "local" });
    mockUsers(USERS);
    vi.mocked(authClient.admin.removeUser).mockResolvedValue({ data: {}, error: null } as never);
    vi.mocked(authClient.admin.setRole).mockResolvedValue({ data: {}, error: null } as never);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<SignInSection />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete kid" }));
    await userEvent.click(screen.getByRole("button", { name: "Make kid admin" }));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(authClient.admin.removeUser).not.toHaveBeenCalled();
    expect(authClient.admin.setRole).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Delete kid" }));
    expect(authClient.admin.removeUser).toHaveBeenCalledWith({ userId: "u" });
    await userEvent.click(screen.getByRole("button", { name: "Make kid admin" }));
    expect(authClient.admin.setRole).toHaveBeenCalledWith({ userId: "u", role: "admin" });
    confirm.mockRestore();
  });
});
