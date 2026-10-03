import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import * as currentUser from "@/lib/current-user";
import { EnforcementSwitch } from "./enforcement";

const asRole = (role: string) => vi.spyOn(currentUser, "useCurrentUser").mockReturnValue({ id: "a", name: "a", role, source: "local" });

beforeEach(() => vi.restoreAllMocks());

it("is hidden from non-admins", () => {
  asRole("user");
  const { container } = render(<EnforcementSwitch mode="dry-run" hasDhcp onChanged={vi.fn()} />);
  expect(container.textContent).toBe("");
});

it("shows the plan summary and switches to apply only after confirmation", async () => {
  asRole("admin");
  vi.spyOn(api, "get").mockResolvedValue({ to_add: ["a", "b"], to_remove: ["c"], failed: [] });
  const post = vi.spyOn(api, "post").mockResolvedValue({ mode: "apply" });
  const onChanged = vi.fn();
  render(<EnforcementSwitch mode="dry-run" hasDhcp onChanged={onChanged} />);
  await userEvent.click(screen.getByRole("button", { name: "Switch to apply…" }));
  expect(api.get).toHaveBeenCalledWith("/sync/plan");
  expect(await screen.findByText(/2 to add · 1 to remove · 0 failed/)).toBeTruthy();
  expect(post).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm apply" }));
  expect(post).toHaveBeenCalledWith("/sync/mode", { mode: "apply" });
  expect(onChanged).toHaveBeenCalled();
});

it("cancel keeps dry-run", async () => {
  asRole("admin");
  vi.spyOn(api, "get").mockResolvedValue({ to_add: [], to_remove: [], failed: [] });
  const post = vi.spyOn(api, "post");
  render(<EnforcementSwitch mode="dry-run" hasDhcp onChanged={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Switch to apply…" }));
  await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Switch to apply…" })).toBeTruthy();
  expect(post).not.toHaveBeenCalled();
});

it("cannot switch to apply without a DHCP provider and goes back to dry-run directly", async () => {
  asRole("admin");
  const { rerender } = render(<EnforcementSwitch mode="dry-run" hasDhcp={false} onChanged={vi.fn()} />);
  expect((screen.getByRole("button", { name: "Switch to apply…" }) as HTMLButtonElement).disabled).toBe(true);
  const post = vi.spyOn(api, "post").mockResolvedValue({ mode: "dry-run" });
  rerender(<EnforcementSwitch mode="apply" hasDhcp onChanged={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Switch to dry-run" }));
  expect(post).toHaveBeenCalledWith("/sync/mode", { mode: "dry-run" });
});

it("shows the backend refusal", async () => {
  asRole("admin");
  vi.spyOn(api, "get").mockRejectedValue(new Error("no DHCP provider with reservations"));
  render(<EnforcementSwitch mode="dry-run" hasDhcp onChanged={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Switch to apply…" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
});
