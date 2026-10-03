import type { NavItem } from "@/lib/nav";
import type { Features, ProviderRole } from "@/lib/types";
import { PROVIDER_UI } from "@/providers/registry";

export type ProviderPill = { tone: "bg-ok" | "bg-bad" | "bg-accent" | "bg-muted"; text: string };

const ROLES: ProviderRole[] = ["dhcp", "dns"];

export function providerPill(features: Features | null, syncMode: "dry-run" | "apply"): ProviderPill {
  const providers = features?.providers;
  if (!providers) return { tone: "bg-muted", text: "Network provider" };
  const { dhcp, dns } = providers;
  if (dns?.down_since) return { tone: "bg-bad", text: "DNS down" };
  if (dhcp?.down_since) return { tone: "bg-bad", text: `${dhcp.label} unreachable` };
  if (!dhcp) return { tone: "bg-muted", text: "No network provider" };
  return syncMode === "apply" ? { tone: "bg-ok", text: `${dhcp.label} DHCP · active` } : { tone: "bg-accent", text: `${dhcp.label} · dry-run` };
}

// Pages a provider adds to the menu, for the role it actually holds: a provider that only serves DNS next to another
// DHCP provider shows none of its DHCP pages.
export function providerNav(features: Features | null): NavItem[] {
  const items: NavItem[] = [];
  const seen = new Set<string>();
  for (const role of ROLES) {
    const ref = features?.providers?.[role];
    if (!ref) continue;
    for (const page of PROVIDER_UI[ref.kind]?.pages ?? []) {
      if (page.role !== role || (page.capability && !ref.capabilities.includes(page.capability))) continue;
      const href = `/integrations/${ref.kind}/${page.slug}`;
      if (seen.has(href)) continue;
      seen.add(href);
      items.push({ href, label: page.label, icon: page.icon });
    }
  }
  return items;
}

export function hasCapability(features: Features | null, role: ProviderRole, capability: string): boolean {
  return Boolean(features?.providers?.[role]?.capabilities.includes(capability));
}

// Without a DHCP provider Janus only records the choice, so every policy stays available. Until features load the
// option stays too: hiding it would reset a group's lan_only default for a moment.
export function lanOnlyAllowed(features: Features | null): boolean {
  const dhcp = features?.providers?.dhcp;
  return !dhcp || Boolean(dhcp.policies?.includes("lan_only"));
}

export function providerSummary(features: Features | null): string {
  const providers = features?.providers;
  if (!providers) return "";
  const { dhcp, dns } = providers;
  if (dhcp && dns && (dns.shared || dns.kind === dhcp.kind)) return `DNS/DHCP ${dhcp.label}`;
  const parts = [dhcp && `DHCP ${dhcp.label}`, dns && `DNS ${dns.label}`].filter(Boolean);
  return parts.length ? parts.join(" · ") : "no network provider";
}
