import { describe, expect, it } from "vitest";

import { buildCells, inPool, poolUsage, rangeUsage } from "@/lib/ipplan";
import { makeDevice, makeGroup } from "@/lib/test-data";

const people = makeGroup({ id: 1, range_start: "192.168.1.10", range_end: "192.168.1.19" });
const devices = [makeDevice({ static_ip: "192.168.1.12" }), makeDevice({ static_ip: null, last_ip: "192.168.1.15" })];

describe("buildCells", () => {
  it("maps 256 addresses to groups, devices and reserved slots", () => {
    const cells = buildCells([people], devices, "192.168.1.1");
    expect(cells).toHaveLength(256);
    expect(cells[12].device?.static_ip).toBe("192.168.1.12");
    expect(cells[12].group?.id).toBe(1);
    expect(cells[15].device).toBeNull();
    expect(cells[20].group).toBeNull();
    expect([cells[0].reserved, cells[1].reserved, cells[255].reserved, cells[2].reserved]).toEqual([true, true, true, false]);
  });
});

describe("rangeUsage", () => {
  it("counts static reservations inside the range", () => {
    expect(rangeUsage(people, devices)).toEqual({ used: 1, total: 10 });
  });
});

describe("guest pool", () => {
  const pool = { start: "192.168.1.200", end: "192.168.1.209" };
  it("tells whether an octet is inside a pool, and treats a missing pool as empty", () => {
    expect([inPool(199, pool), inPool(200, pool), inPool(209, pool), inPool(210, pool)]).toEqual([false, true, true, false]);
    expect(inPool(200, null)).toBe(false);
  });
  it("counts guests leasing an address inside the pool", () => {
    const guests = [makeDevice({ static_ip: null, last_ip: "192.168.1.201" }), makeDevice({ static_ip: null, last_ip: "192.168.1.245" }),
      makeDevice({ static_ip: null, last_ip: null })];
    expect(poolUsage(pool, guests)).toEqual({ used: 1, total: 10 });
  });
});
