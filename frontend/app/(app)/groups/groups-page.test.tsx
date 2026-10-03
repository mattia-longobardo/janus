import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import GroupsPage from "@/app/(app)/groups/page";
import { ApiError, api } from "@/lib/api";
import * as featuresModule from "@/lib/features";
import * as settingsModule from "@/lib/settings-context";
import { GUEST_COLOR, GuestIconDefault, guestLook } from "@/lib/group-icons";
import { makeGroup } from "@/lib/test-data";
import type { Features, GuestSettings, ProviderRef } from "@/lib/types";

const GROUPS = [makeGroup({ id: 1, name: "People" }), makeGroup({ id: 2, name: "Power meters", default_access: "lan_only" })];

const state = vi.hoisted(() => ({
  rules: { auto_remove_hours: null, inactive_remove_hours: 6, color: "#4FC3D9", icon: "guest" } as GuestSettings,
  reloadRules: async () => {},
  rulesError: null as string | null,
}));
const NONE: never[] = [];

vi.mock("@/lib/use-resource", () => ({
  useResource: (path: string) => ({
    data: path === "/groups" ? GROUPS : path === "/guests/settings" ? state.rules : NONE,
    error: path === "/guests/settings" ? state.rulesError : null,
    loading: false,
    reload: path === "/guests/settings" ? state.reloadRules : async () => {},
  }),
}));

const pihole: ProviderRef = { kind: "pihole", label: "Pi-hole", capabilities: ["reservations", "quarantine"], policies: ["full", "lan_only"], down_since: null };
const unifi: ProviderRef = { kind: "unifi", label: "UniFi", capabilities: ["reservations"], policies: ["full"], down_since: null };

function show(features: Features) {
  vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features, reload: async () => {} });
  render(<GroupsPage />);
}

const accessOptions = () => [...screen.getByRole("group", { name: "Default access" }).querySelectorAll("button")].map((b) => b.textContent);

describe("GroupsPage follows the DHCP provider", () => {
  it("lists the quarantine pool and offers LAN only with Pi-hole", async () => {
    show({ providers: { dhcp: pihole, dns: null } });
    expect(screen.getAllByText("Quarantine").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /People/ }));
    expect(accessOptions()).toEqual(["Full network", "LAN only"]);
  });

  it("hides the quarantine row and LAN only with UniFi, except on a group that already has it", async () => {
    show({ providers: { dhcp: unifi, dns: null } });
    expect(screen.queryByText("Quarantine")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /People/ }));
    expect(accessOptions()).toEqual(["Full network"]);
    await userEvent.click(screen.getByRole("button", { name: /Power meters/ }));
    expect(accessOptions()).toEqual(["Full network", "LAN only"]);
  });
});

describe("GroupsPage hours inputs", () => {
  it("shows the unit inside the input as a suffix", async () => {
    show({ providers: { dhcp: pihole, dns: null } });
    await userEvent.click(screen.getByRole("button", { name: /People/ }));
    for (const label of ["Offline hours", "Scan interval hours"]) {
      const wrapper = screen.getByLabelText(label).parentElement as HTMLElement;
      expect(wrapper.querySelector("[data-suffix]")?.textContent).toBe("h");
    }
  });
});

describe("guestLook", () => {
  it("falls back to the default look for an invalid colour or an unknown icon", () => {
    const look = guestLook({ guests: { enabled: true, pool: false, color: "red", icon: "nope" } });
    expect(look.color).toBe(GUEST_COLOR);
    expect(look.Icon).toBe(GuestIconDefault);
    expect(guestLook({ guests: { enabled: true, pool: false, color: "#E58FB8", icon: "" } }).Icon).toBe(GuestIconDefault);
  });
});

describe("GroupsPage guests editor", () => {
  const guests: Features = { providers: { dhcp: null, dns: null }, guests: { enabled: true, pool: false, color: "#4FC3D9", icon: "guest" } };

  function openGuests(features: Features = guests) {
    show(features);
    return userEvent.click(screen.getByRole("button", { name: /^Guests/ }));
  }

  it("opens from the Guests row with the guest look, pool and rules", async () => {
    state.rules = { auto_remove_hours: null, inactive_remove_hours: 6, color: "#4FC3D9", icon: "guest" };
    await openGuests();
    expect(screen.getByRole("heading", { name: "Guests" })).toBeTruthy();
    expect((screen.getByLabelText("Name") as HTMLInputElement).readOnly).toBe(true);
    // The default guest colour is not in the palette, so it shows as the custom colour.
    expect((screen.getByLabelText("Custom colour") as HTMLInputElement).value.toUpperCase()).toBe("#4FC3D9");
    expect(screen.getByRole("button", { name: "Icon guest" }).getAttribute("aria-pressed")).toBe("true");
    expect((screen.getByLabelText("Hours not seen") as HTMLInputElement).value).toBe("6");
    expect((screen.getByLabelText("Hours after added") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("A guest's own expiry replaces both rules.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open guests list" }).getAttribute("href")).toBe("/guests");
    expect(screen.queryByRole("button", { name: /Delete/ })).toBeNull();
    const wrapper = screen.getByLabelText("Hours after added").parentElement as HTMLElement;
    expect(wrapper.querySelector("[data-suffix]")?.textContent).toBe("h");
  });

  it("saves the pool to settings and the rules and look to the guest settings", async () => {
    state.rules = { auto_remove_hours: null, inactive_remove_hours: 6, color: "#4FC3D9", icon: "guest" };
    const put = vi.spyOn(api, "put").mockResolvedValue({});
    await openGuests();
    await userEvent.type(screen.getByLabelText("Range start"), "192.168.1.200");
    await userEvent.type(screen.getByLabelText("Range end"), "192.168.1.229");
    await userEvent.click(screen.getByRole("button", { name: "Color #E58FB8" }));
    await userEvent.click(screen.getByRole("button", { name: "Icon phone" }));
    await userEvent.click(screen.getByLabelText("Remove guests after a fixed time"));
    expect((screen.getByLabelText("Hours after added") as HTMLInputElement).value).toBe("24");
    await userEvent.click(screen.getByLabelText("Remove guests not seen for a while"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    expect(put).toHaveBeenNthCalledWith(1, "/settings", { network: { guest_start: "192.168.1.200", guest_end: "192.168.1.229" } });
    expect(put).toHaveBeenNthCalledWith(2, "/guests/settings", {
      auto_remove_hours: 24,
      inactive_remove_hours: null,
      color: "#E58FB8",
      icon: "phone",
    });
    expect(await screen.findByText("Guests saved.")).toBeTruthy();
  });

  it("sends only the guest settings when the pool is unchanged", async () => {
    state.rules = { auto_remove_hours: 24, inactive_remove_hours: null, color: "#4FC3D9", icon: "guest" };
    const put = vi.spyOn(api, "put").mockResolvedValue({});
    await openGuests();
    const hours = screen.getByLabelText("Hours after added");
    await userEvent.clear(hours);
    await userEvent.type(hours, "48");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/guests/settings", { auto_remove_hours: 48, inactive_remove_hours: null, color: "#4FC3D9", icon: "guest" }),
    );
    expect(put).toHaveBeenCalledTimes(1);
  });

  it("asks for valid hours instead of saving", async () => {
    state.rules = { auto_remove_hours: null, inactive_remove_hours: null, color: "#4FC3D9", icon: "guest" };
    const put = vi.spyOn(api, "put").mockResolvedValue({});
    await openGuests();
    await userEvent.click(screen.getByLabelText("Remove guests not seen for a while"));
    const hours = screen.getByLabelText("Hours not seen");
    await userEvent.clear(hours);
    await userEvent.type(hours, "9000");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Enter the hours as a whole number between 1 and 8760.");
    expect(put).not.toHaveBeenCalled();
  });

  it("shows a refused pool under its field and leaves the guest settings alone", async () => {
    state.rules = { auto_remove_hours: null, inactive_remove_hours: null, color: "#4FC3D9", icon: "guest" };
    const put = vi.spyOn(api, "put").mockRejectedValue(new ApiError(422, "guest_end: set it together with guest_start, or clear both"));
    await openGuests();
    await userEvent.type(screen.getByLabelText("Range start"), "192.168.1.200");
    await userEvent.click(screen.getByLabelText("Remove guests after a fixed time"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const error = await screen.findByText("set it together with guest_start, or clear both");
    expect(error.id).toBe(screen.getByLabelText("Range end").getAttribute("aria-describedby"));
    expect(put).toHaveBeenCalledTimes(1);
  });

  it("reloads settings and features after a saved pool even when the guest settings are refused", async () => {
    state.rules = { auto_remove_hours: null, inactive_remove_hours: null, color: "#4FC3D9", icon: "guest" };
    const reloadSettings = vi.fn(async () => {});
    const reloadFeatures = vi.fn(async () => {});
    vi.spyOn(settingsModule, "useSettings").mockReturnValue({ settings: settingsModule.DEFAULT_SETTINGS, reload: reloadSettings });
    vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features: guests, reload: reloadFeatures });
    vi.spyOn(api, "put").mockImplementation(async (path: string) => {
      if (path === "/guests/settings") throw new ApiError(422, "hours must be a whole number between 1 and 8760");
      return {};
    });
    render(<GroupsPage />);
    await userEvent.click(screen.getByRole("button", { name: /^Guests/ }));
    await userEvent.type(screen.getByLabelText("Range start"), "192.168.1.200");
    await userEvent.type(screen.getByLabelText("Range end"), "192.168.1.229");
    await userEvent.click(screen.getByLabelText("Remove guests after a fixed time"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect((await screen.findByRole("alert")).textContent).toBe("hours must be a whole number between 1 and 8760");
    expect(reloadSettings).toHaveBeenCalled();
    expect(reloadFeatures).toHaveBeenCalled();
  });

  it("draws the Guests row with the configured look and pool", () => {
    vi.spyOn(settingsModule, "useSettings").mockReturnValue({
      settings: { ...settingsModule.DEFAULT_SETTINGS, network: { ...settingsModule.DEFAULT_SETTINGS.network, guest_start: "192.168.1.200", guest_end: "192.168.1.229" } },
      reload: async () => {},
    });
    show({ ...guests, guests: { enabled: true, pool: true, color: "#E58FB8", icon: "phone" } });
    const row = screen.getByRole("button", { name: /^Guests/ });
    expect(row.textContent).toContain(".200–.229");
    expect((row.querySelector("[aria-hidden]") as HTMLElement).style.color).toBe("rgb(229, 143, 184)");
  });

  it("keeps the refused rule and look edits when only the pool was saved", async () => {
    state.rules = { auto_remove_hours: null, inactive_remove_hours: null, color: "#4FC3D9", icon: "guest" };
    let current = settingsModule.DEFAULT_SETTINGS;
    const reloadSettings = vi.fn(async () => {
      current = { ...current, network: { ...current.network, guest_start: "192.168.1.200", guest_end: "192.168.1.229" } };
    });
    vi.spyOn(settingsModule, "useSettings").mockImplementation(() => ({ settings: current, reload: reloadSettings }));
    vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features: guests, reload: async () => {} });
    vi.spyOn(api, "put").mockImplementation(async (path: string) => {
      if (path === "/guests/settings") throw new ApiError(422, "icon: too long");
      return {};
    });
    render(<GroupsPage />);
    await userEvent.click(screen.getByRole("button", { name: /^Guests/ }));
    await userEvent.type(screen.getByLabelText("Range start"), "192.168.1.200");
    await userEvent.type(screen.getByLabelText("Range end"), "192.168.1.229");
    await userEvent.click(screen.getByRole("button", { name: "Color #E58FB8" }));
    await userEvent.click(screen.getByLabelText("Remove guests after a fixed time"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect((await screen.findByRole("alert")).textContent).toBe("icon: too long");
    expect(reloadSettings).toHaveBeenCalled();
    expect((screen.getByLabelText("Range start") as HTMLInputElement).value).toBe("192.168.1.200");
    expect((screen.getByLabelText("Remove guests after a fixed time") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("button", { name: "Color #E58FB8" }).getAttribute("aria-pressed")).toBe("true");
    expect((screen.getByRole("button", { name: "Save changes" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("says when the guest settings cannot be loaded", async () => {
    state.rules = undefined as unknown as GuestSettings;
    state.rulesError = "Server error";
    try {
      await openGuests();
      expect(screen.getByRole("alert").textContent).toBe("Guest settings could not be loaded: Server error");
    } finally {
      state.rulesError = null;
    }
  });
});
