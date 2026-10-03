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

import type { Device, Group } from "@/lib/types";

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
};

export const PENDING_COLOR = "#E0A84E";
export const NEUTRAL_COLOR = "#9AA3A8";
export const GUEST_COLOR = "#4FC3D9";
export const GuestIcon = UserRound;

export function iconFor(key: string | undefined): LucideIcon {
  return (key && GROUP_ICONS[key]) || Monitor;
}

export function deviceLook(device: Device, groups: Group[]): { Icon: LucideIcon; color: string } {
  if (device.access === "pending") return { Icon: Clock3, color: PENDING_COLOR };
  if (device.access === "guest") return { Icon: GuestIcon, color: GUEST_COLOR };
  const group = groups.find((g) => g.id === device.group_id);
  if (!group) return { Icon: Router, color: NEUTRAL_COLOR };
  return { Icon: iconFor(group.icon), color: group.color };
}

export { Clock3 as QuarantineIcon, Globe as ModemIcon, Router as GatewayIcon };
