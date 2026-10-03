import type { Device, Group } from "@/lib/types";

export interface Cell {
  octet: number;
  group: Group | null;
  device: Device | null;
  reserved: boolean;
}

export function lastOctet(ip: string): number {
  return Number(ip.split(".")[3]);
}

export function buildCells(groups: Group[], devices: Device[], gatewayIp: string): Cell[] {
  const byOctet = new Map<number, Device>();
  for (const device of devices) {
    if (device.static_ip) byOctet.set(lastOctet(device.static_ip), device);
  }
  const gateway = lastOctet(gatewayIp);
  return Array.from({ length: 256 }, (_, octet) => ({
    octet,
    group: groups.find((g) => lastOctet(g.range_start) <= octet && octet <= lastOctet(g.range_end)) ?? null,
    device: byOctet.get(octet) ?? null,
    reserved: octet === 0 || octet === 255 || octet === gateway,
  }));
}

export function rangeUsage(group: Group, devices: Device[]): { used: number; total: number } {
  const start = lastOctet(group.range_start);
  const end = lastOctet(group.range_end);
  const used = devices.filter((d) => d.static_ip && lastOctet(d.static_ip) >= start && lastOctet(d.static_ip) <= end).length;
  return { used, total: end - start + 1 };
}

export type Pool = { start: string; end: string };

// The guest pool is optional: an empty start or end means there is none.
export function guestPool(network: { guest_start: string; guest_end: string }): Pool | null {
  return network.guest_start && network.guest_end ? { start: network.guest_start, end: network.guest_end } : null;
}

export function inPool(octet: number, pool: Pool | null): boolean {
  return pool !== null && lastOctet(pool.start) <= octet && octet <= lastOctet(pool.end);
}

// Guests have no reservation: what counts is the address they currently lease.
export function poolUsage(pool: Pool, guests: Device[]): { used: number; total: number } {
  const used = guests.filter((g) => g.last_ip && inPool(lastOctet(g.last_ip), pool)).length;
  return { used, total: lastOctet(pool.end) - lastOctet(pool.start) + 1 };
}
