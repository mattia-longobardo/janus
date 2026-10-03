import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApproveForm } from "@/components/approve-form";
import * as featuresModule from "@/lib/features";
import { makeDevice, makeGroup } from "@/lib/test-data";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("ApproveForm", () => {
  const device = makeDevice({ id: "dev-1", name: "Unknown 00:53:40", dhcp_hostname: "pixel-7", access: "pending", group_id: null, static_ip: null });
  const groups = [
    makeGroup({ id: 1, name: "People" }),
    makeGroup({ id: 2, name: "Power meters", range_start: "192.168.1.120", range_end: "192.168.1.129", default_access: "lan_only" }),
  ];

  it("needs an explicit group, proposes the next free IP and posts the approval", async () => {
    let free = "192.168.1.12";
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/groups/1/next-free-ip")) return json(200, { ip: free });
      if (url.endsWith("/devices/dev-1/approve")) return json(200, { device: { ...device, access: "authorized" }, enforcement: "dry-run" });
      throw new Error(`unexpected ${url} ${init?.method}`);
    });
    const onApproved = vi.fn();
    render(<ApproveForm device={device} groups={groups} onApproved={onApproved} />);
    const submit = screen.getByRole("button", { name: "Approve and assign IP" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText("Group"), "1");
    const ip = screen.getByLabelText("Static IP") as HTMLInputElement;
    await waitFor(() => expect(ip.value).toBe("192.168.1.12"));
    free = "192.168.1.13";
    await userEvent.clear(ip);
    await userEvent.click(screen.getByRole("button", { name: "Next free" }));
    await waitFor(() => expect(ip.value).toBe("192.168.1.13"));
    const name = screen.getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "PHONE_B");
    await userEvent.click(submit);
    await waitFor(() => expect(onApproved).toHaveBeenCalled());
    const approveCall = fetchSpy.mock.calls.find(([url]) => String(url).endsWith("/approve"))!;
    expect(JSON.parse(String(approveCall[1]?.body))).toEqual({ name: "PHONE_B", group_id: 1, static_ip: "192.168.1.13", access: "authorized" });
  });

  it("follows the group's default access and shows backend errors", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("next-free-ip")) return json(200, { ip: "192.168.1.121" });
      return json(422, { detail: "192.168.1.121 is already reserved" });
    });
    render(<ApproveForm device={device} groups={groups} onApproved={vi.fn()} />);
    await userEvent.selectOptions(screen.getByLabelText("Group"), "2");
    expect((screen.getByLabelText("LAN only") as HTMLInputElement).checked).toBe(true);
    await waitFor(() => expect((screen.getByLabelText("Static IP") as HTMLInputElement).value).toBe("192.168.1.121"));
    await userEvent.click(screen.getByRole("button", { name: "Approve and assign IP" }));
    expect((await screen.findByRole("alert")).textContent).toBe("192.168.1.121 is already reserved");
    const body = JSON.parse(String(fetchSpy.mock.calls.find(([url]) => String(url).endsWith("/approve"))![1]?.body));
    expect(body.access).toBe("lan_only");
  });

  it("blocks when Block is chosen", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(json(200, { device: { ...device, access: "blocked" }, enforcement: "dry-run" }));
    const onBlocked = vi.fn();
    render(<ApproveForm device={device} groups={groups} onApproved={vi.fn()} onBlocked={onBlocked} />);
    await userEvent.click(screen.getByLabelText("Block"));
    await userEvent.click(screen.getByRole("button", { name: "Block device" }));
    await waitFor(() => expect(onBlocked).toHaveBeenCalled());
    expect(String(fetchSpy.mock.calls[0][0])).toBe("/api/devices/dev-1/block");
  });

  it("hides LAN only when the DHCP provider cannot enforce it, even as a group default", async () => {
    const dhcp = { kind: "unifi", label: "UniFi", capabilities: ["reservations"], policies: ["full"], down_since: null };
    vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features: { providers: { dhcp, dns: null } }, reload: async () => {} });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(200, { ip: "192.168.1.121" }));
    render(<ApproveForm device={device} groups={groups} onApproved={vi.fn()} />);
    expect(screen.queryByLabelText("LAN only")).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("Group"), "2");
    expect((screen.getByLabelText("Full network") as HTMLInputElement).checked).toBe(true);
  });

  it("offers Approve as guest only when guests are enabled", () => {
    vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features: { guests: { enabled: false, pool: false } }, reload: async () => {} });
    render(<ApproveForm device={device} groups={groups} onApproved={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Approve as guest" })).toBeNull();
  });

  it("admits the device as a guest with the chosen expiry, without a group", async () => {
    vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features: { guests: { enabled: true, pool: true } }, reload: async () => {} });
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/guests/settings")) return json(200, { auto_remove_hours: 24, inactive_remove_hours: null });
      if (url.endsWith("/devices/dev-1/guest")) return json(200, { ...device, access: "guest" });
      throw new Error(`unexpected ${url}`);
    });
    const onGuest = vi.fn();
    render(<ApproveForm device={device} groups={groups} onApproved={vi.fn()} onGuest={onGuest} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve as guest" }));
    expect(await screen.findByRole("button", { name: "Use default (24 h)" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "3 days" }));
    await userEvent.click(screen.getByRole("button", { name: "Add as guest" }));
    await waitFor(() => expect(onGuest).toHaveBeenCalled());
    const call = fetchSpy.mock.calls.find(([url]) => String(url).endsWith("/devices/dev-1/guest"))!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({ name: "pixel-7", expires_in_hours: 72 });
  });

  it("sends no expiry when the guest keeps the default", async () => {
    vi.spyOn(featuresModule, "useFeatures").mockReturnValue({ features: { guests: { enabled: true, pool: true } }, reload: async () => {} });
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/guests/settings")) return json(200, { auto_remove_hours: null, inactive_remove_hours: null });
      return json(422, { detail: "device: already a authorized device" });
    });
    render(<ApproveForm device={device} groups={groups} onApproved={vi.fn()} onGuest={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve as guest" }));
    await userEvent.click(await screen.findByRole("button", { name: "Never" }));
    await userEvent.click(screen.getByRole("button", { name: "Add as guest" }));
    expect((await screen.findByRole("alert")).textContent).toBe("device: already a authorized device");
    const call = fetchSpy.mock.calls.find(([url]) => String(url).endsWith("/devices/dev-1/guest"))!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({ name: "pixel-7" });
  });
});
