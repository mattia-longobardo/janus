import { deviceIp, ipSortKey } from "@/lib/format";
import type { Device, Group, MapLink } from "@/lib/types";

export const TIER_W = 176;
export const TIER_H = 44;
export const NODE_W = 236;
export const NODE_H = 40;
export const BOX_W = 256;
export const BOX_HEADER = 34;
export const BOX_PAD = 10;
const NODE_STEP = 46;
const BOX_GAP = 24;
const COLUMN_STEP = 270;
const COLUMNS = 4;
const LEFT = 24;
const MODEM_Y = 20;
const GATEWAY_Y = 88;
const INFRA_Y = 168;
const INFRA_STEP = 200;
const TIER_STEP = 80;
const GROUPS_GAP = 52;
const MAX_DEPTH = 6;
const INFRA_ICONS = new Set(["wifi", "router", "server"]);
const ACCESS_POINT_ICONS = new Set(["wifi", "router"]);

export type Role = "gateway" | "infra" | "member";

export interface Topology {
  role: Map<string, Role>;
  parent: Map<string, string | null>;
  depth: Map<string, number>;
  treeLinks: Set<number>;
}

export interface Point {
  x: number;
  y: number;
}

export interface Box extends Point {
  key: string;
  w: number;
  h: number;
}

export type Segment = [number, number, number, number];

export interface Wires {
  modem: Point;
  solid: Segment[];
  dashed: Segment[];
  badge: Point | null;
}

function groupOf(device: Device, groups: Group[]): Group | undefined {
  return groups.find((g) => g.id === device.group_id);
}

function baseRole(device: Device, groups: Group[], gatewayIp: string): Role {
  if (deviceIp(device) === gatewayIp) return "gateway";
  if (device.access === "pending") return "member";
  const group = groupOf(device, groups);
  return group && INFRA_ICONS.has(group.icon) ? "infra" : "member";
}

export function topology(devices: Device[], groups: Group[], gatewayIp: string, links: MapLink[] = []): Topology {
  const role = new Map<string, Role>();
  const parent = new Map<string, string | null>();
  const depth = new Map<string, number>();
  const treeLinks = new Set<number>();
  for (const d of devices) role.set(d.id, baseRole(d, groups, gatewayIp));
  const pending = new Set(devices.filter((d) => d.access === "pending").map((d) => d.id));
  const wired = new Map<string, { other: string; id: number }[]>();
  for (const link of links) {
    if (link.kind !== "wired" || !role.has(link.source_id) || !role.has(link.target_id)) continue;
    wired.set(link.source_id, [...(wired.get(link.source_id) ?? []), { other: link.target_id, id: link.id }]);
    wired.set(link.target_id, [...(wired.get(link.target_id) ?? []), { other: link.source_id, id: link.id }]);
  }
  const gateway = devices.find((d) => role.get(d.id) === "gateway");
  const queue: string[] = [];
  if (gateway) {
    depth.set(gateway.id, 0);
    parent.set(gateway.id, null);
    queue.push(gateway.id);
  }
  for (const d of devices.filter((x) => role.get(x.id) === "infra")) {
    depth.set(d.id, 1);
    parent.set(d.id, gateway?.id ?? null);
    queue.push(d.id);
  }
  while (queue.length > 0) {
    const current = queue.shift()!;
    const level = depth.get(current) ?? 0;
    for (const { other, id } of wired.get(current) ?? []) {
      if (pending.has(other) || role.get(other) === "gateway") continue;
      if (depth.has(other)) {
        if (parent.get(other) === current) treeLinks.add(id);
        continue;
      }
      if (level + 1 > MAX_DEPTH) continue;
      depth.set(other, level + 1);
      parent.set(other, current);
      role.set(other, "infra");
      treeLinks.add(id);
      queue.push(other);
    }
  }
  return { role, parent, depth, treeLinks };
}

export function roleOf(device: Device, groups: Group[], gatewayIp: string, topo?: Topology): Role {
  return topo?.role.get(device.id) ?? baseRole(device, groups, gatewayIp);
}

export function nodeSize(role: Role): { w: number; h: number } {
  return role === "member" ? { w: NODE_W, h: NODE_H } : { w: TIER_W, h: TIER_H };
}

export function groupKey(device: Device): string {
  if (device.access === "pending") return "pending";
  if (device.group_id == null) return "ungrouped";
  return `g${device.group_id}`;
}

const byIp = (a: Device, b: Device) => ipSortKey(deviceIp(a)) - ipSortKey(deviceIp(b)) || a.name.localeCompare(b.name);

export function autoLayout(devices: Device[], groups: Group[], gatewayIp: string, links: MapLink[] = []): Record<string, Point> {
  const topo = topology(devices, groups, gatewayIp, links);
  const positions: Record<string, Point> = {};
  const role = (d: Device) => topo.role.get(d.id) ?? "member";
  const maxDepth = Math.max(1, ...devices.filter((d) => role(d) === "infra").map((d) => topo.depth.get(d.id) ?? 1));
  const groupsY = INFRA_Y + (maxDepth - 1) * TIER_STEP + TIER_H + GROUPS_GAP;

  const members = devices.filter((d) => role(d) === "member");
  const order = [
    ...[...groups].sort((a, b) => ipSortKey(a.range_start) - ipSortKey(b.range_start)).map((g) => `g${g.id}`),
    "ungrouped",
    "pending",
  ];
  const buckets = new Map<string, Device[]>(order.map((key) => [key, []]));
  for (const device of members) buckets.get(groupKey(device))?.push(device);
  const filled = order.filter((key) => (buckets.get(key) ?? []).length > 0);
  const columns = Math.max(1, Math.min(COLUMNS, filled.length));
  const heights = new Array<number>(columns).fill(groupsY);
  for (const key of filled) {
    const list = (buckets.get(key) ?? []).sort(byIp);
    const column = heights.indexOf(Math.min(...heights));
    const x = LEFT + column * COLUMN_STEP + BOX_PAD;
    let y = heights[column] + BOX_HEADER;
    for (const device of list) {
      positions[device.id] = { x, y };
      y += NODE_STEP;
    }
    heights[column] = y - NODE_STEP + NODE_H + BOX_PAD + BOX_GAP;
  }

  const width = LEFT + columns * COLUMN_STEP - (COLUMN_STEP - BOX_W);
  const center = Math.max(width / 2, TIER_W);
  const gateway = devices.find((d) => role(d) === "gateway");
  if (gateway) positions[gateway.id] = { x: center - TIER_W / 2, y: GATEWAY_Y };

  for (let level = 1; level <= maxDepth; level += 1) {
    const row = devices.filter((d) => role(d) === "infra" && (topo.depth.get(d.id) ?? 1) === level);
    const y = INFRA_Y + (level - 1) * TIER_STEP;
    if (level === 1) {
      row.sort(byIp);
      const start = center - ((row.length - 1) * INFRA_STEP) / 2 - TIER_W / 2;
      row.forEach((device, i) => {
        positions[device.id] = { x: start + i * INFRA_STEP, y };
      });
      continue;
    }
    const byParent = new Map<string, Device[]>();
    for (const d of row) {
      const key = topo.parent.get(d.id) ?? "";
      byParent.set(key, [...(byParent.get(key) ?? []), d]);
    }
    const parents = [...byParent.keys()].sort((a, b) => (positions[a]?.x ?? 0) - (positions[b]?.x ?? 0));
    let nextFree = -Infinity;
    for (const parentId of parents) {
      const children = (byParent.get(parentId) ?? []).sort(byIp);
      const parentX = positions[parentId]?.x ?? center - TIER_W / 2;
      let x = Math.max(parentX - ((children.length - 1) * INFRA_STEP) / 2, nextFree);
      for (const child of children) {
        positions[child.id] = { x, y };
        x += INFRA_STEP;
      }
      nextFree = x;
    }
  }
  return positions;
}

export function groupBoxes(
  devices: Device[],
  groups: Group[],
  gatewayIp: string,
  positions: Record<string, Point>,
  links: MapLink[] = [],
): Box[] {
  const topo = topology(devices, groups, gatewayIp, links);
  const boxes = new Map<string, Box>();
  for (const device of devices) {
    const p = positions[device.id];
    if (!p || roleOf(device, groups, gatewayIp, topo) !== "member") continue;
    const key = groupKey(device);
    const left = p.x - BOX_PAD;
    const top = p.y - BOX_HEADER;
    const right = p.x + NODE_W + BOX_PAD;
    const bottom = p.y + NODE_H + BOX_PAD;
    const box = boxes.get(key);
    if (!box) {
      boxes.set(key, { key, x: left, y: top, w: right - left, h: bottom - top });
      continue;
    }
    const x = Math.min(box.x, left);
    const y = Math.min(box.y, top);
    box.w = Math.max(box.x + box.w, right) - x;
    box.h = Math.max(box.y + box.h, bottom) - y;
    box.x = x;
    box.y = y;
  }
  return [...boxes.values()];
}

export function wires(
  devices: Device[],
  groups: Group[],
  gatewayIp: string,
  positions: Record<string, Point>,
  boxes: Box[],
  links: MapLink[] = [],
): Wires {
  const topo = topology(devices, groups, gatewayIp, links);
  const solid: Segment[] = [];
  const dashed: Segment[] = [];
  const role = (d: Device) => topo.role.get(d.id) ?? "member";
  const gateway = devices.find((d) => role(d) === "gateway" && positions[d.id]);
  const infra = devices.filter((d) => role(d) === "infra" && positions[d.id]);
  const centerX = (p: Point) => p.x + TIER_W / 2;

  const gp = gateway ? positions[gateway.id] : null;
  const modem = gp ? { x: gp.x, y: gp.y - (GATEWAY_Y - MODEM_Y) } : { x: (boxes[0]?.x ?? LEFT) + 200, y: MODEM_Y };
  const hub = gp ?? modem;
  if (gp) solid.push([centerX(modem), modem.y + TIER_H, centerX(gp), gp.y]);

  const children = new Map<string, Point[]>();
  for (const d of infra) {
    const parentId = topo.parent.get(d.id);
    const key = parentId && positions[parentId] ? parentId : "hub";
    children.set(key, [...(children.get(key) ?? []), positions[d.id]]);
  }
  for (const [parentId, kids] of children) {
    const from = parentId === "hub" ? hub : positions[parentId];
    const railY = Math.min(...kids.map((k) => k.y)) - 18;
    const xs = [...kids.map(centerX), centerX(from)];
    solid.push([centerX(from), from.y + TIER_H, centerX(from), railY]);
    solid.push([Math.min(...xs), railY, Math.max(...xs), railY]);
    for (const k of kids) solid.push([centerX(k), railY, centerX(k), k.y]);
  }

  if (boxes.length === 0) return { modem, solid, dashed, badge: null };
  const busY = Math.min(...boxes.map((b) => b.y)) - 24;
  const feeders = infra.filter((d) => ACCESS_POINT_ICONS.has(groupOf(d, groups)?.icon ?? ""));
  const sources = feeders.length > 0 ? feeders.map((d) => positions[d.id]) : [hub];
  const sourceXs: number[] = [];
  for (const p of sources) {
    const x = centerX(p);
    sourceXs.push(x);
    dashed.push([x, p.y + TIER_H, x, busY]);
  }

  const columns: { x: number; boxes: Box[] }[] = [];
  for (const box of [...boxes].sort((a, b) => a.x - b.x)) {
    const column = columns.find((c) => Math.abs(c.x - box.x) < 60);
    if (column) {
      column.boxes.push(box);
      column.x = Math.min(column.x, box.x);
    } else columns.push({ x: box.x, boxes: [box] });
  }
  const spines: number[] = [];
  for (const column of columns) {
    const spineX = column.x - 8;
    spines.push(spineX);
    const headers = column.boxes.map((b) => b.y + BOX_HEADER / 2);
    dashed.push([spineX, busY, spineX, Math.max(...headers)]);
    for (const box of column.boxes) dashed.push([spineX, box.y + BOX_HEADER / 2, box.x, box.y + BOX_HEADER / 2]);
  }
  const busLeft = Math.min(...spines, ...sourceXs);
  const busRight = Math.max(...spines, ...sourceXs);
  dashed.push([busLeft, busY, busRight, busY]);
  return { modem, solid, dashed, badge: { x: busLeft + 22, y: busY - 11 } };
}

export const PHONE_ZOOM = 0.8;
const PHONE_TOP = 56;

// Phones start at a readable zoom on the top of the topology (ISP modem, gateway, first tier), centred on the
// modem, instead of shrinking the whole graph into a 390px canvas; the user pans and pinches from there.
export function phoneViewport(modem: Point, canvasWidth: number, zoom = PHONE_ZOOM): { x: number; y: number; zoom: number } {
  return { x: canvasWidth / 2 - (modem.x + TIER_W / 2) * zoom, y: PHONE_TOP - modem.y * zoom, zoom };
}
