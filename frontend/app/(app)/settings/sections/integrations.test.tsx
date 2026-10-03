// frontend/app/(app)/settings/sections/integrations.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { IntegrationsSection } from "./integrations";

const VIEW = {
  gotify: { values: { url: "", token: false }, source: { url: "env", token: "env" }, ready: false },
  email: { values: { host: "", port: 465, security: "ssl", user: "", password: false, sender: "" },
           source: { host: "env", port: "env", security: "env", user: "env", password: "env", sender: "env" }, ready: false },
};

describe("IntegrationsSection", () => {
  it("sends only the fields the user changed, secrets included", async () => {
    vi.spyOn(api, "get").mockResolvedValue(VIEW);
    const put = vi.spyOn(api, "put").mockResolvedValue({ ...VIEW, gotify: { ...VIEW.gotify, ready: true } });
    render(<IntegrationsSection />);
    await userEvent.type(await screen.findByLabelText("Gotify URL"), "https://g.example");
    await userEvent.click(screen.getByRole("button", { name: "Change Gotify token" }));
    await userEvent.type(screen.getByLabelText("Gotify token"), "tok");
    await userEvent.click(screen.getByRole("button", { name: "Save integrations" }));
    expect(put).toHaveBeenCalledWith("/notifications/channels", { gotify: { url: "https://g.example", token: "tok" } });
    expect(await screen.findByText(/Gotify · ready/)).toBeTruthy();
  });

  it("clears a stored secret with an empty string and shows backend 422 detail", async () => {
    const set = { ...VIEW, email: { ...VIEW.email, values: { ...VIEW.email.values, password: true } } };
    vi.spyOn(api, "get").mockResolvedValue(set);
    const put = vi.spyOn(api, "put").mockRejectedValue(new ApiError(422, "port: must be between 1 and 65535"));
    render(<IntegrationsSection />);
    await userEvent.click(await screen.findByRole("button", { name: "Clear SMTP password" }));
    await userEvent.click(screen.getByRole("button", { name: "Save integrations" }));
    expect(put).toHaveBeenCalledWith("/notifications/channels", { email: { password: "" } });
    expect(await screen.findByText("port: must be between 1 and 65535")).toBeTruthy();
  });

  it("keeps Save disabled until something changes", async () => {
    vi.spyOn(api, "get").mockResolvedValue(VIEW);
    render(<IntegrationsSection />);
    const save = (await screen.findByRole("button", { name: "Save integrations" })) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
  });
});
