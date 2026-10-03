export type Access = "authorized" | "lan_only" | "pending" | "blocked";

export interface Device {
  id: string;
  mac: string | null;
  name: string;
  hostname: string;
  group_id: number | null;
  static_ip: string | null;
  access: Access;
  vendor: string | null;
  private_mac: boolean;
  online: boolean;
  last_ip: string | null;
  dhcp_hostname: string | null;
  first_seen: string | null;
  last_seen: string | null;
  last_scan_at: string | null;
  issues: { kind: string; severity: "critical" | "warning"; message: string }[];
  health: "ok" | "warning" | "critical";
}

export interface Group {
  id: number;
  name: string;
  color: string;
  icon: string;
  range_start: string;
  range_end: string;
  default_access: Access;
  offline_alert_hours: number | null;
  device_count: number;
  scan_enabled: boolean;
  scan_interval_hours: number;
}

export interface EventItem {
  id: number;
  ts: string;
  type: string;
  mac: string | null;
  payload: Record<string, unknown>;
}

export interface FactValue {
  value: string;
  source: string;
  confidence: number;
  observed_at: string;
}

export interface Facts {
  summary: Record<string, FactValue>;
  facts: (FactValue & { field: string })[];
}

export interface ServiceItem {
  port: number;
  proto: string;
  state: string;
  service: string | null;
  version: string | null;
  risk: "none" | "warning" | "high";
  risk_reason: string | null;
  muted: boolean;
  first_seen: string;
  last_seen: string;
}

export interface DnsActivity {
  total: number;
  sampled: number;
  truncated: boolean;
  blocked: number;
  domains: { domain: string; count: number; blocked: boolean }[];
}

export interface NotifySettings {
  enabled: boolean;
  quiet_start: string | null;
  quiet_end: string | null;
  email_enabled: boolean;
  email_recipient: string;
  gotify_enabled: boolean;
}

export interface Rule {
  event_type: string;
  label: string;
  email: boolean;
  gotify: boolean;
  priority: number;
  default_priority: number;
}

export interface MaintenanceWindow {
  id: number;
  name: string;
  start_time: string;
  duration_min: number;
  days: number;
  enabled: boolean;
  mute_alerts: boolean;
  pause_isolation: boolean;
}

export type NetworkField =
  | "subnet"
  | "gateway"
  | "quarantine_start"
  | "quarantine_end"
  | "pihole_url"
  | "sentinel_interface"
  | "sweep_interval_s"
  | "scan_window_start"
  | "scan_window_end";

export interface AppSettings {
  timezone: string;
  time_format: "24h" | "12h";
  sync_mode: "dry-run" | "apply";
  network: {
    subnet: string;
    gateway: string;
    quarantine_start: string;
    quarantine_end: string;
    pihole_url: string;
    sentinel_interface: string;
    sweep_interval_s: number;
  };
  scan_window: { start: string; end: string };
  source?: Partial<Record<NetworkField, "env" | "custom">>;
  status: {
    pihole_down_since: string | null;
    dns_down_since: string | null;
    sentinel_down_since: string | null;
    last_sweep_at: string | null;
    maintenance_active: boolean;
  };
  channels: { gotify_url: string; email_sender: string };
}

export interface MapLink {
  id: number;
  source_id: string;
  target_id: string;
  kind: "wired" | "wifi";
  label: string | null;
}

export interface MapData {
  layout_version: number;
  positions: { device_id: string; x: number; y: number }[];
  links: MapLink[];
}

export interface Approval {
  device: Device;
  enforcement: string;
}

export interface ProviderRef {
  kind: string;
  label: string;
  capabilities: string[];
  down_since: string | null;
}

export interface ProvidersFeature {
  dhcp: ProviderRef | null;
  dns: ProviderRef | null;
}

export interface Features {
  notify?: { email: boolean; gotify: boolean };
  providers?: ProvidersFeature;
  guests?: { enabled: boolean };
}

// --- A ---
export type ChannelState<V> = { values: V; source: Record<keyof V, "env" | "custom">; ready: boolean };
export type GotifyValues = { url: string; token: boolean };
export type EmailValues = {
  host: string;
  port: number;
  security: "ssl" | "starttls" | "none";
  user: string;
  password: boolean;
  sender: string;
};
export type ChannelsView = { gotify: ChannelState<GotifyValues>; email: ChannelState<EmailValues> };
