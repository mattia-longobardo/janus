import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { GuestsSection } from "./guests";

describe("GuestsSection", () => {
  it("saves the pool and both rules with one Save", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ auto_remove_hours: null, inactive_remove_hours: 6 });
    const put = vi.spyOn(api, "put").mockResolvedValue({});
    render(<GuestsSection />);
    const save = screen.getByRole("button", { name: "Save guest settings" }) as HTMLButtonElement;
    await waitFor(() => expect((screen.getByLabelText("Hours not seen") as HTMLInputElement).value).toBe("6"));
    expect(save.disabled).toBe(true);
    await userEvent.type(screen.getByLabelText("Guest pool from"), "192.168.1.200");
    await userEvent.type(screen.getByLabelText("Guest pool to"), "192.168.1.229");
    await userEvent.click(screen.getByLabelText("Remove guests after a fixed time"));
    expect((screen.getByLabelText("Hours after added") as HTMLInputElement).value).toBe("24");
    await userEvent.click(screen.getByLabelText("Remove guests not seen for a while"));
    await userEvent.click(save);
    expect(put).toHaveBeenCalledWith("/settings", { network: { guest_start: "192.168.1.200", guest_end: "192.168.1.229" } });
    expect(put).toHaveBeenCalledWith("/guests/settings", { auto_remove_hours: 24, inactive_remove_hours: null });
    expect(await screen.findByText("Guest settings saved.")).toBeTruthy();
    expect(screen.getByText("A guest's own expiry replaces both rules.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /reset/i })).toBeNull();
  });

  it("shows the backend 422 and leaves the rules alone when the pool is refused", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ auto_remove_hours: null, inactive_remove_hours: null });
    const put = vi.spyOn(api, "put").mockRejectedValue(new ApiError(422, "guest_end: set it together with guest_start, or clear both"));
    render(<GuestsSection />);
    await userEvent.type(await screen.findByLabelText("Guest pool from"), "192.168.1.200");
    await userEvent.click(screen.getByLabelText("Remove guests after a fixed time"));
    await userEvent.click(screen.getByRole("button", { name: "Save guest settings" }));
    expect((await screen.findByRole("alert")).textContent).toBe("guest_end: set it together with guest_start, or clear both");
    expect(put).toHaveBeenCalledTimes(1);
  });

  it("sends only the rules when the pool is unchanged", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ auto_remove_hours: 24, inactive_remove_hours: null });
    const put = vi.spyOn(api, "put").mockResolvedValue({});
    render(<GuestsSection />);
    const hours = screen.getByLabelText("Hours after added") as HTMLInputElement;
    await waitFor(() => expect(hours.disabled).toBe(false));
    await userEvent.clear(hours);
    await userEvent.type(hours, "48");
    await userEvent.click(screen.getByRole("button", { name: "Save guest settings" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/guests/settings", { auto_remove_hours: 48, inactive_remove_hours: null }));
    expect(put).toHaveBeenCalledTimes(1);
  });
});
