import type { LucideIcon } from "lucide-react";
import { Bell, Clock3, Grid2x2, House, Layers, Monitor, NotepadText, Settings, Share2 } from "lucide-react";

import type { Features } from "@/lib/types";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  count?: "all" | "pending" | "guests";
  requires?: (f: Features) => boolean;
};

export const NAV: NavItem[] = [
  { href: "/", label: "Overview", icon: House },
  { href: "/map", label: "Network map", icon: Share2 },
  { href: "/devices", label: "Devices", icon: Monitor, count: "all" },
  { href: "/pending", label: "Pending", icon: Clock3, count: "pending" },
  { href: "/ip-plan", label: "IP plan", icon: Grid2x2 },
  { href: "/groups", label: "Groups", icon: Layers },
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/events", label: "Event log", icon: NotepadText },
  { href: "/settings", label: "Settings", icon: Settings },
];

// Gated items stay hidden until the features response arrives, so the menu never flashes entries that then disappear.
export function visibleNav(features: Features | null, extra: NavItem[] = []): NavItem[] {
  const at = NAV.findIndex((i) => i.href === "/notifications");
  const items = [...NAV.slice(0, at), ...extra, ...NAV.slice(at)];
  return items.filter((i) => !i.requires || (features !== null && i.requires(features)));
}
