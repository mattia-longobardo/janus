import { describe, expect, it } from "vitest";

import { describeEvent } from "@/lib/events";

const event = (type: string, payload: Record<string, unknown> = {}) => ({ id: 1, ts: "2026-10-01T10:00:00Z", type, mac: null, payload });

describe("describeEvent", () => {
  it.each([
    [event("device.new", { hostname: "pixel-7", ip: "192.168.1.243" }), "New device pixel-7 on 192.168.1.243"],
    [event("device.new", {}), "New device on no IP yet"],
    [event("device.approved", { name: "TV", ip: "192.168.1.153", access: "lan_only" }), "Approved TV → 192.168.1.153 (LAN only)"],
    [event("device.ip_mismatch", { name: "CAM", ip: "192.168.1.170", expected: "192.168.1.101" }), "CAM uses 192.168.1.170, reserved 192.168.1.101"],
    [event("sync.applied", { added: ["a", "b"], removed: ["c"] }), "DHCP reservations: +2 −1"],
    [event("sync.failed", { failed: ["a"] }), "The DHCP provider refused 1 reservation(s)"],
    [event("security.risky_service", { ports: [{ port: 23 }, { port: 21 }] }), "Risky services on ports 23, 21"],
    [event("infra.down", { service: "pihole" }), "Pi-hole unreachable"],
    [event("infra.down", { service: "pihole_dns" }), "Pi-hole DNS unreachable"],
    [event("infra.down", { service: "dhcp", provider: "UniFi" }), "UniFi DHCP unreachable"],
    [event("infra.up", { service: "dns", provider: "Pi-hole" }), "Pi-hole DNS reachable again"],
    [event("infra.down", { service: "dhcp" }), "DHCP unreachable"],
    [event("ip.conflict", { ip: "192.168.1.155", reserved: true, claimant: { name: "TV_KITCHEN", mac: "00:00:5E:00:53:70" }, owner: { name: "TV_SALA", mac: "00:00:5E:00:53:71" } }),
      "TV_KITCHEN (00:00:5E:00:53:70) tried to take 192.168.1.155, assigned to TV_SALA (00:00:5E:00:53:71)"],
    [event("ip.conflict", { ip: "192.168.1.10" }), "IP conflict on 192.168.1.10"],
    [event("maintenance.start"), "Maintenance window started"],
    [event("guest.added", { name: "Anna phone", mac: "00:00:5E:00:53:20", expires_at: null }), "Guest Anna phone added"],
    [event("guest.expired", { name: "Anna phone", mac: "00:00:5E:00:53:20", last_ip: "192.168.1.201" }), "Guest Anna phone expired"],
    [event("guest.removed", { name: "Anna phone", mac: "00:00:5E:00:53:20", last_ip: null }), "Guest Anna phone removed"],
    [event("something.else"), "something.else"],
  ])("%j", (input, expected) => {
    expect(describeEvent(input)).toBe(expected);
  });
});
