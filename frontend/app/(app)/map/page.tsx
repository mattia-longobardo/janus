"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  ConnectionMode,
  BackgroundVariant,
  type Connection,
  type Edge,
  Handle,
  type Node,
  type NodeChange,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
} from "@xyflow/react";
import clsx from "clsx";
import { toPng } from "html-to-image";
import { AlertTriangle, Maximize, Minus, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { HEALTH_COLOR, healthTitle } from "@/components/health";
import { useResolvedTheme } from "@/components/theme-toggle";
import { Button, Notice, PageHeader } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { useFeatures } from "@/lib/features";
import { deviceIp } from "@/lib/format";
import { GatewayIcon, ModemIcon, NEUTRAL_COLOR, PENDING_COLOR, deviceLook } from "@/lib/group-icons";
import {
  type Box,
  type Point,
  type Wires,
  autoLayout,
  groupBoxes,
  groupKey,
  nodeSize,
  roleOf,
  topology,
  wires,
} from "@/lib/map-layout";
import { hasCapability } from "@/lib/provider-status";
import { useSettings } from "@/lib/settings-context";
import type { Device, Group, MapData } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const LAYOUT_VERSION = 3;
const FIT = { padding: { top: "96px", right: "24px", bottom: "72px", left: "24px" } } as const;
type DeviceData = { device: Device; groups: Group[]; showIp: boolean; w: number; h: number; gateway: boolean };
type BoxData = { label: string; color: string; range: string; count: number; pending: boolean };
type ModemData = { w: number; h: number };
type WireData = { wires: Wires; width: number; height: number };

function Tile({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span className="flex size-6 shrink-0 items-center justify-center rounded-md" style={{ background: `${color}26`, color }}>
      {children}
    </span>
  );
}

function DeviceNode({ data }: NodeProps<Node<DeviceData>>) {
  const d = data.device;
  const wrongIp = d.issues.some((issue) => issue.kind === "ip_mismatch");
  const shownIp = wrongIp ? d.last_ip : deviceIp(d);
  const pending = d.access === "pending";
  const look = deviceLook(d, data.groups);
  const color = data.gateway ? "#C9CDD0" : look.color;
  const Icon = data.gateway ? GatewayIcon : look.Icon;
  return (
    <div
      className={clsx("group relative flex items-center gap-[9px] rounded-lg bg-card pl-2 pr-2.5", !d.online && !pending && "opacity-55")}
      style={{
        width: data.w,
        height: data.h,
        border: pending ? "1.5px dashed var(--accent)" : `1px solid ${color}66`,
        boxShadow: d.health !== "ok" ? `0 0 0 2px ${HEALTH_COLOR[d.health]}` : undefined,
      }}
      title={[`${d.name} · ${shownIp ?? "no IP"}`, healthTitle(d)].filter(Boolean).join("\n")}
    >
      <Handle type="target" position={Position.Top} className="!size-3 !border-[1.5px] !border-accent !bg-card !opacity-0 group-hover:!opacity-100" />
      <Tile color={color}>
        <Icon className="size-3.5" strokeWidth={1.8} />
      </Tile>
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="truncate text-xs font-semibold leading-tight text-text">{d.name}</span>
        {data.showIp && (
          <span className={clsx("truncate font-mono text-[10.5px] leading-tight", wrongIp ? "text-bad" : "text-faint")}>{shownIp ?? "—"}</span>
        )}
      </span>
      {d.health !== "ok" ? (
        <AlertTriangle className="size-3.5 shrink-0" style={{ color: HEALTH_COLOR[d.health] }} strokeWidth={2.4} aria-label="Needs attention" />
      ) : (
        <span className={clsx("size-2 shrink-0 rounded-full", pending ? "bg-accent" : d.online ? "bg-ok" : "bg-off")} />
      )}
      <Handle type="source" position={Position.Bottom} className="!size-3 !border-[1.5px] !border-accent !bg-card !opacity-0 group-hover:!opacity-100" />
    </div>
  );
}

function ModemNode({ data }: NodeProps<Node<ModemData>>) {
  return (
    <div
      className="flex items-center gap-[9px] overflow-hidden rounded-lg bg-card pl-2 pr-2.5"
      style={{ width: data.w, height: data.h, border: `1px solid ${NEUTRAL_COLOR}66` }}
    >
      <Tile color={NEUTRAL_COLOR}>
        <ModemIcon className="size-3.5" strokeWidth={1.8} />
      </Tile>
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="truncate text-xs font-semibold leading-tight text-text">ISP modem</span>
        <span className="truncate font-mono text-[10.5px] leading-tight text-faint">WAN</span>
      </span>
      <span className="size-2 shrink-0 rounded-full bg-ok" />
    </div>
  );
}

function BoxNode({ data }: NodeProps<Node<BoxData>>) {
  return (
    <div
      className="h-full w-full rounded-xl"
      style={
        data.pending
          ? { border: "1.5px dashed var(--accent-line)", background: "var(--accent-soft)" }
          : { border: "1px solid var(--line)", background: `${data.color}0D` }
      }
    >
      <div className="flex items-center gap-2 px-3 pt-[9px] text-[12.5px] font-semibold leading-4 text-text">
        <span className="size-[9px] rounded-[3px]" style={{ background: data.color }} />
        <span className="truncate">{data.label}</span>
        <span className="ml-auto shrink-0 font-mono text-[10.5px] font-normal text-faint">
          {data.range ? `${data.range} · ` : ""}
          {data.count}
        </span>
      </div>
    </div>
  );
}

function WireNode({ data }: NodeProps<Node<WireData>>) {
  const { wires: w } = data;
  return (
    <svg width={data.width} height={data.height} className="pointer-events-none overflow-visible" aria-hidden>
      {w.solid.map(([x1, y1, x2, y2], i) => (
        <line key={`s${i}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--line2)" strokeWidth={1.5} />
      ))}
      {w.dashed.map(([x1, y1, x2, y2], i) => (
        <line key={`d${i}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--ok)" strokeWidth={1.5} strokeDasharray="5 4" />
      ))}
      {w.badge && (
        <foreignObject x={w.badge.x} y={w.badge.y} width={90} height={22}>
          <span className="inline-block rounded-full border border-line2 bg-canvas px-2 font-mono text-[10.5px] leading-[18px] text-ok">
            Wi-Fi · LAN
          </span>
        </foreignObject>
      )}
    </svg>
  );
}

const nodeTypes = { device: DeviceNode, box: BoxNode, modem: ModemNode, wires: WireNode };

function lastOctets(group: Group): string {
  return `.${group.range_start.split(".")[3]}–.${group.range_end.split(".")[3]}`;
}

function MapCanvas() {
  const flow = useReactFlow();
  const router = useRouter();
  const theme = useResolvedTheme();
  const { settings } = useSettings();
  const { features } = useFeatures();
  const quarantine = hasCapability(features, "dhcp", "quarantine");
  const gatewayIp = settings.network.gateway;
  const devicesRes = useResource<Device[]>("/devices", { refreshMs: 15_000 });
  const groupsRes = useResource<Group[]>("/groups");
  const mapRes = useResource<MapData>("/map");
  const [positions, setPositions] = useState<Record<string, Point>>({});
  const [dirty, setDirty] = useState(false);
  const [showIp, setShowIp] = useState(true);
  const [linkKind, setLinkKind] = useState<"wired" | "wifi">("wired");
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string }>();
  const groups = useMemo(() => groupsRes.data ?? [], [groupsRes.data]);
  const devices = useMemo(() => (devicesRes.data ?? []).filter((d) => d.access !== "blocked"), [devicesRes.data]);
  const links = useMemo(() => mapRes.data?.links ?? [], [mapRes.data]);
  const topo = useMemo(() => topology(devices, groups, gatewayIp, links), [devices, groups, gatewayIp, links]);

  useEffect(() => {
    if (!devicesRes.data || !groupsRes.data || !mapRes.data) return;
    const saved =
      mapRes.data.layout_version === LAYOUT_VERSION
        ? Object.fromEntries(mapRes.data.positions.map((p) => [p.device_id, { x: p.x, y: p.y }]))
        : {};
    const auto = autoLayout(devices, groups, gatewayIp, mapRes.data.links);
    setPositions((current) => ({ ...auto, ...saved, ...current }));
  }, [devicesRes.data, groupsRes.data, mapRes.data, devices, groups, gatewayIp]);

  const [fitted, setFitted] = useState(false);
  useEffect(() => {
    if (fitted || Object.keys(positions).length === 0) return;
    const id = window.setTimeout(() => {
      void flow.fitView(FIT);
      setFitted(true);
    }, 80);
    return () => window.clearTimeout(id);
  }, [fitted, positions, flow]);

  const boxes = useMemo(() => groupBoxes(devices, groups, gatewayIp, positions, links), [devices, groups, gatewayIp, positions, links]);
  const wiring = useMemo(
    () => wires(devices, groups, gatewayIp, positions, boxes, links),
    [devices, groups, gatewayIp, positions, boxes, links],
  );

  const boxInfo = useCallback(
    (box: Box): BoxData => {
      const count = devices.filter((d) => roleOf(d, groups, gatewayIp, topo) === "member" && groupKey(d) === box.key).length;
      if (box.key === "pending") {
        // Without a quarantine pool pending devices keep whatever address they got: no range to show.
        if (!quarantine) return { label: "Pending", color: PENDING_COLOR, range: "", count, pending: true };
        const range = `.${settings.network.quarantine_start.split(".")[3]}–.${settings.network.quarantine_end.split(".")[3]}`;
        return { label: "Quarantine", color: PENDING_COLOR, range, count, pending: true };
      }
      const group = groups.find((g) => `g${g.id}` === box.key);
      if (!group) return { label: "Unassigned", color: NEUTRAL_COLOR, range: "", count, pending: false };
      return { label: group.name, color: group.color, range: lastOctets(group), count, pending: false };
    },
    [devices, groups, gatewayIp, quarantine, settings.network.quarantine_start, settings.network.quarantine_end],
  );

  const deviceData = useMemo(() => {
    const data = new Map<string, DeviceData>();
    for (const d of devices) {
      const role = roleOf(d, groups, gatewayIp, topo);
      data.set(d.id, { device: d, groups, showIp, gateway: role === "gateway", ...nodeSize(role) });
    }
    return data;
  }, [devices, groups, gatewayIp, showIp]);

  const nodes = useMemo<Node[]>(() => {
    const extent = Object.values(positions).reduce((acc, p) => ({ w: Math.max(acc.w, p.x + 300), h: Math.max(acc.h, p.y + 120) }), { w: 0, h: 0 });
    const list: Node[] = [
      {
        id: "wires",
        type: "wires",
        position: { x: 0, y: 0 },
        data: { wires: wiring, width: extent.w, height: extent.h },
        draggable: false,
        selectable: false,
        connectable: false,
        focusable: false,
        zIndex: -2,
        style: { pointerEvents: "none" },
      },
      ...boxes.map<Node<BoxData>>((box) => ({
        id: `box:${box.key}`,
        type: "box",
        position: { x: box.x, y: box.y },
        data: boxInfo(box),
        style: { width: box.w, height: box.h },
        draggable: false,
        selectable: false,
        connectable: false,
        zIndex: -1,
      })),
      {
        id: "modem",
        type: "modem",
        position: wiring.modem,
        data: nodeSize("gateway"),
        draggable: false,
        selectable: false,
        connectable: false,
      },
    ];
    for (const d of devices) {
      const data = deviceData.get(d.id);
      if (!positions[d.id] || !data) continue;
      list.push({ id: d.id, type: "device", position: positions[d.id], data, width: data.w, height: data.h });
    }
    return list;
  }, [devices, positions, boxes, wiring, boxInfo, deviceData]);

  const [flowNodes, setFlowNodes] = useState<Node[]>([]);
  useEffect(() => {
    setFlowNodes((previous) => {
      const known = new Map(previous.map((n) => [n.id, n]));
      return nodes.map((n) => {
        const old = known.get(n.id);
        return old ? { ...n, measured: old.measured, selected: old.selected, dragging: old.dragging } : n;
      });
    });
  }, [nodes]);

  const edges = useMemo<Edge[]>(
    () =>
      links.map((link) => {
        const inTree = topo.treeLinks.has(link.id);
        return {
          id: `link:${link.id}`,
          source: link.source_id,
          target: link.target_id,
          type: inTree ? "step" : "smoothstep",
          label: link.label ?? undefined,
          interactionWidth: 16,
          className: inTree ? "janus-tree-edge" : undefined,
          style: {
            stroke: inTree ? "transparent" : link.kind === "wifi" ? "var(--ok)" : "var(--line2)",
            strokeWidth: 1.5,
            strokeDasharray: link.kind === "wifi" ? "5 4" : undefined,
          },
        };
      }),
    [links, topo],
  );

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setFlowNodes((current) => applyNodeChanges(changes, current));
    const moves = changes.filter((c) => c.type === "position" && c.position);
    if (moves.length === 0) return;
    setPositions((current) => {
      const next = { ...current };
      for (const change of moves) {
        if (change.type === "position" && change.position && current[change.id]) next[change.id] = change.position;
      }
      return next;
    });
    setDirty(true);
  }, []);

  const onConnect = async (connection: Connection) => {
    const { source, target } = connection;
    if (!source || !target || !positions[source] || !positions[target]) return;
    try {
      await api.post("/map/links", { source_id: source, target_id: target, kind: linkKind });
      await relayout();
    } catch (err) {
      setMessage({ tone: "error", text: errorText(err) });
    }
  };

  const onEdgeClick = async (_: unknown, edge: Edge) => {
    if (!window.confirm("Remove this uplink?")) return;
    try {
      await api.del(`/map/links/${edge.id.replace("link:", "")}`);
      await relayout();
    } catch (err) {
      setMessage({ tone: "error", text: errorText(err) });
    }
  };

  async function relayout() {
    const fresh = await api.get<MapData>("/map");
    const next = autoLayout(devices, groups, gatewayIp, fresh.links);
    setPositions(next);
    await api.put("/map/positions", devices.filter((d) => next[d.id]).map((d) => ({ device_id: d.id, ...next[d.id] })));
    setDirty(false);
    await mapRes.reload();
    window.setTimeout(() => void flow.fitView(FIT), 80);
  }

  async function openDevice(node: Node) {
    if (!positions[node.id]) return;
    if (dirty) await save();
    router.push(`/devices/${node.id}?from=map`);
  }

  function arrange() {
    setPositions(autoLayout(devices, groups, gatewayIp, links));
    setDirty(true);
    window.setTimeout(() => void flow.fitView(FIT), 50);
  }

  async function save() {
    try {
      const body = devices.filter((d) => positions[d.id]).map((d) => ({ device_id: d.id, ...positions[d.id] }));
      await api.put("/map/positions", body);
      setDirty(false);
      setMessage({ tone: "success", text: "Layout saved." });
      await mapRes.reload();
    } catch (err) {
      setMessage({ tone: "error", text: errorText(err) });
    }
  }

  async function exportPng() {
    const element = document.querySelector<HTMLElement>(".react-flow__viewport")?.closest<HTMLElement>(".react-flow");
    if (!element) return;
    const url = await toPng(element, { backgroundColor: getComputedStyle(element).backgroundColor });
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "janus-map.png";
    anchor.click();
  }

  const online = devices.filter((d) => d.online && d.access !== "pending").length;
  const pending = devices.filter((d) => d.access === "pending").length;
  const offline = devices.filter((d) => !d.online && d.access !== "pending").length;

  return (
    <>
      <PageHeader
        title="Network map"
        subtitle="topology · drag nodes, draw uplinks, groups follow the IP plan"
        actions={
          <>
            <Button onClick={arrange}>Auto layout</Button>
            <Button aria-pressed={showIp} onClick={() => setShowIp((v) => !v)}>
              {showIp ? "Hide IPs" : "Show IPs"}
            </Button>
            <Button onClick={() => void exportPng()}>Export PNG</Button>
            <Button variant="primary" disabled={!dirty} onClick={() => void save()}>
              Save layout
            </Button>
          </>
        }
      />
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {(devicesRes.error || mapRes.error) && <Notice tone="error">{devicesRes.error ?? mapRes.error}</Notice>}
      <div
        className="relative h-[calc(100dvh-190px)] min-h-[560px] overflow-hidden rounded-[14px] border border-line"
        style={{ backgroundColor: "var(--canvas)" }}
      >
        <ReactFlow
          nodes={flowNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onConnect={onConnect}
          onEdgeClick={onEdgeClick}
          onNodeDoubleClick={(_, node) => void openDevice(node)}
          zoomOnDoubleClick={false}
          connectionMode={ConnectionMode.Loose}
          connectionRadius={60}
          connectionLineStyle={{ stroke: linkKind === "wifi" ? "var(--ok)" : "var(--accent)", strokeWidth: 1.5, strokeDasharray: linkKind === "wifi" ? "5 4" : undefined }}
          colorMode={theme}
          fitView
          fitViewOptions={FIT}
          minZoom={0.2}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
          style={{ background: "transparent" }}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color="var(--dotgrid)" />
        </ReactFlow>

        <div className="absolute left-4 top-4 z-10 flex items-start gap-2.5">
          <div className="flex flex-col gap-1.5">
            {[
              { label: "Zoom in", Icon: Plus, run: () => void flow.zoomIn() },
              { label: "Zoom out", Icon: Minus, run: () => void flow.zoomOut() },
              { label: "Fit to screen", Icon: Maximize, run: () => void flow.fitView(FIT) },
            ].map(({ label, Icon, run }) => (
              <button
                key={label}
                type="button"
                aria-label={label}
                title={label}
                onClick={run}
                className="flex size-10 items-center justify-center rounded-lg border border-line2 bg-card text-text"
              >
                <Icon className="size-4" />
              </button>
            ))}
          </div>
          <dl className="grid grid-cols-[auto_auto] gap-x-[22px] gap-y-1 rounded-[14px] border border-line bg-card px-3.5 py-3 text-[13px]">
            <dt className="text-muted">Total</dt>
            <dd className="font-mono">{devices.length}</dd>
            <dt className="text-ok">Online</dt>
            <dd className="font-mono">{online}</dd>
            <dt className="text-muted">Offline</dt>
            <dd className="font-mono">{offline}</dd>
            <dt className="text-accent-text">Pending</dt>
            <dd className="font-mono">{pending}</dd>
          </dl>
        </div>

        <div className="absolute right-4 top-4 z-10 flex w-[150px] flex-col gap-2 rounded-[14px] border border-line bg-card px-3.5 py-3 text-xs text-muted">
          <span className="flex items-center gap-2">
            <span className="w-[26px] border-t-[1.5px] border-line2" />
            Wired
          </span>
          <span className="flex items-center gap-2">
            <span className="w-[26px] border-t-[1.5px] border-dashed border-ok" />
            Wi-Fi / LAN
          </span>
          <span className="flex items-center gap-2">
            <span className="size-3.5 rounded border-[1.5px] border-dashed border-accent" />
            Pending
          </span>
          <span className="flex items-center gap-2">
            <span className="size-3.5 rounded border border-line2 bg-card opacity-55" />
            Offline
          </span>
        </div>
        <div className="absolute bottom-4 left-4 z-10 flex max-w-[260px] flex-col gap-1.5 rounded-[14px] border border-line bg-card px-3.5 py-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted">New uplink</span>
            <div role="group" aria-label="New uplink type" className="flex gap-1">
              {(["wired", "wifi"] as const).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={linkKind === kind}
                  onClick={() => setLinkKind(kind)}
                  className={clsx(
                    "h-7 rounded-md border px-2.5 text-[11px]",
                    linkKind === kind ? "border-accent bg-accent-soft text-text" : "border-line2 text-muted",
                  )}
                >
                  {kind === "wired" ? "Wired" : "Wi-Fi"}
                </button>
              ))}
            </div>
          </div>
          <span className="text-[10.5px] leading-snug text-faint">Drag from a node’s bottom edge to another node. Click a line to remove it.</span>
        </div>
        {dirty && (
          <span className="absolute bottom-4 right-4 z-10 rounded-full border border-accent-line bg-accent-soft px-3 py-1 text-xs text-accent-text">
            Unsaved layout
          </span>
        )}
      </div>
    </>
  );
}

export default function MapPage() {
  return (
    <ReactFlowProvider>
      <MapCanvas />
    </ReactFlowProvider>
  );
}

