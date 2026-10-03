import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { GuestExpiry } from "@/components/guest-expiry";

it("emits a duration for presets and a date for the picker", async () => {
  const onChange = vi.fn();
  render(<GuestExpiry onChange={onChange} />);
  await userEvent.click(screen.getByRole("button", { name: "1 day" }));
  expect(onChange).toHaveBeenLastCalledWith({ expires_in_hours: 24 });
  await userEvent.click(screen.getByRole("button", { name: "Pick a date" }));
  await userEvent.type(screen.getByLabelText("Expiry date"), "2026-10-10");
  expect(onChange).toHaveBeenLastCalledWith({ expires_on: "2026-10-10" });
  await userEvent.click(screen.getByRole("button", { name: "Never" }));
  expect(onChange).toHaveBeenLastCalledWith({ clear_expiry: true });
});

it("offers the global rule instead of Never when one is set", async () => {
  const onChange = vi.fn();
  render(<GuestExpiry onChange={onChange} rules={{ auto_remove_hours: 24, inactive_remove_hours: null }} />);
  expect(screen.queryByRole("button", { name: "Never" })).toBeNull();
  const fallback = screen.getByRole("button", { name: "Use default (24 h)" });
  expect(fallback.getAttribute("aria-pressed")).toBe("true");
  await userEvent.click(screen.getByRole("button", { name: "2 hours" }));
  await userEvent.click(fallback);
  expect(onChange).toHaveBeenLastCalledWith({ clear_expiry: true });
});

it("names both rules and keeps a guest's own expiry unselected", () => {
  const value = { guest_expires_at: "2026-10-10T21:59:59Z" };
  render(<GuestExpiry onChange={vi.fn()} value={value} rules={{ auto_remove_hours: 24, inactive_remove_hours: 6 }} />);
  expect(screen.getByRole("button", { name: "Use default (24 h / 6 h idle)" }).getAttribute("aria-pressed")).toBe("false");
});
