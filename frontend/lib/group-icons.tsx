import {
  Activity,
  Clock3,
  Globe,
  House,
  type LucideIcon,
  Monitor,
  Printer,
  Router,
  Server,
  Smartphone,
  Tv,
  UserRound,
  Wifi,
  Zap,
} from "lucide-react";

import type { Device, Features, Group } from "@/lib/types";

export const GROUP_ICONS: Record<string, LucideIcon> = {
  device: Monitor,
  phone: Smartphone,
  home: House,
  zap: Zap,
  activity: Activity,
  tv: Tv,
  printer: Printer,
  server: Server,
  wifi: Wifi,
  router: Router,
  guest: UserRound,
};

export const PENDING_COLOR = "#E0A84E";
export const NEUTRAL_COLOR = "#9AA3A8";
// The guests' default look; the configured one comes with the guests feature (set in Groups).
export const GUEST_COLOR = "#4FC3D9";
export const GUEST_ICON = "guest";

export type Look = { Icon: LucideIcon; color: string };

export function iconFor(key: string | undefined): LucideIcon {
  return (key && GROUP_ICONS[key]) || Monitor;
}

export function guestLook(features: Features | null | undefined): Look {
  return { Icon: iconFor(features?.guests?.icon ?? GUEST_ICON), color: features?.guests?.color ?? GUEST_COLOR };
}

export function deviceLook(device: Device, groups: Group[], guest: Look = guestLook(null)): Look {
  if (device.access === "pending") return { Icon: Clock3, color: PENDING_COLOR };
  if (device.access === "guest") return guest;
  const group = groups.find((g) => g.id === device.group_id);
  if (!group) return { Icon: Router, color: NEUTRAL_COLOR };
  return { Icon: iconFor(group.icon), color: group.color };
}

export { Clock3 as QuarantineIcon, Globe as ModemIcon, Router as GatewayIcon };
