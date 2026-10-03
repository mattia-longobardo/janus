import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import * as featuresModule from "@/lib/features";
import * as settingsModule from "@/lib/settings-context";
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

  it("reloads settings and features after a saved pool even when the rules are refused", async () => {
    const reloadSettings = vi.fn(async () => {});
    const reloadFeatures = vi.fn(async () => {});
    vi.spyOn(settingsModule, "useSettings").mockReturnValue({ settings: settingsModule.DEFAULT_SETTINGS, reload: reloadSettings });
    vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features: null, reload: reloadFeatures });
    vi.spyOn(api, "get").mockResolvedValue({ auto_remove_hours: null, inactive_remove_hours: null });
    vi.spyOn(api, "put").mockImplementation(async (path: string) => {
      if (path === "/guests/settings") throw new ApiError(422, "hours must be a whole number between 1 and 8760");
      return {};
    });
    render(<GuestsSection />);
    await userEvent.type(await screen.findByLabelText("Guest pool from"), "192.168.1.200");
    await userEvent.type(screen.getByLabelText("Guest pool to"), "192.168.1.229");
    await userEvent.click(screen.getByLabelText("Remove guests after a fixed time"));
    await userEvent.click(screen.getByRole("button", { name: "Save guest settings" }));
    expect((await screen.findByRole("alert")).textContent).toBe("hours must be a whole number between 1 and 8760");
    expect(reloadSettings).toHaveBeenCalled();
    expect(reloadFeatures).toHaveBeenCalled();
  });

  it("asks for the hours instead of sending an empty rule", async () => {
    vi.spyOn(api, "get").mockResolvedValue({ auto_remove_hours: null, inactive_remove_hours: null });
    const put = vi.spyOn(api, "put").mockResolvedValue({});
    render(<GuestsSection />);
    const hours = screen.getByLabelText("Hours not seen") as HTMLInputElement;
    await userEvent.click(await screen.findByLabelText("Remove guests not seen for a while"));
    await userEvent.clear(hours);
    await userEvent.click(screen.getByRole("button", { name: "Save guest settings" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Enter the hours as a whole number between 1 and 8760.");
    expect(put).not.toHaveBeenCalled();
  });
});
