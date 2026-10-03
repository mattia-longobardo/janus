import { describe, expect, it } from "vitest";

import { lanOnlyAllowed, providerNav, providerPill, providerSummary } from "@/lib/provider-status";

const ref = (over = {}) => ({ kind: "pihole", label: "Pi-hole", capabilities: [], policies: [], down_since: null, ...over });

describe("providerPill", () => {
  it("names the configured provider", () => {
    expect(providerPill({ providers: { dhcp: ref(), dns: ref() } }, "apply").text).toBe("Pi-hole DHCP · active");
    expect(providerPill({ providers: { dhcp: ref({ kind: "unifi", label: "UniFi" }), dns: null } }, "dry-run").text).toBe("UniFi · dry-run");
  });
  it("reports outages first", () => {
    expect(providerPill({ providers: { dhcp: ref({ down_since: "x" }), dns: ref() } }, "apply")).toEqual({ tone: "bg-bad", text: "Pi-hole unreachable" });
    expect(providerPill({ providers: { dhcp: ref(), dns: ref({ down_since: "x" }) } }, "apply").text).toBe("DNS down");
  });
  it("says when nothing is configured", () => {
    expect(providerPill({ providers: { dhcp: null, dns: null } }, "dry-run").text).toBe("No network provider");
  });
});

describe("providerNav", () => {
  it("shows Pi-hole DHCP pages only when Pi-hole holds the DHCP role", () => {
    const pihole = (role: "dhcp" | "dns") => ref({ capabilities: role === "dhcp" ? ["reservations", "dhcp_server", "quarantine"] : ["dns_query_log", "dns_probe"] });
    expect(providerNav({ providers: { dhcp: pihole("dhcp"), dns: { ...pihole("dns"), shared: true } } }).map((i) => i.href)).toEqual(["/integrations/pihole/cutover"]);
    expect(providerNav({ providers: { dhcp: ref({ kind: "unifi", label: "UniFi", capabilities: ["reservations"] }), dns: pihole("dns") } })
      .some((i) => i.href === "/integrations/pihole/cutover")).toBe(false);
  });
  it("shows nothing until features load or for providers without pages", () => {
    expect(providerNav(null)).toEqual([]);
    expect(providerNav({ providers: { dhcp: ref({ kind: "acme", capabilities: ["dhcp_server"] }), dns: null } })).toEqual([]);
  });
});

describe("feature gates", () => {
  it("offers LAN only when the DHCP provider supports it or when there is none", () => {
    expect(lanOnlyAllowed({ providers: { dhcp: ref({ policies: ["full", "lan_only"] }), dns: null } })).toBe(true);
    expect(lanOnlyAllowed({ providers: { dhcp: ref({ kind: "unifi", label: "UniFi", policies: ["full"] }), dns: null } })).toBe(false);
    expect(lanOnlyAllowed({ providers: { dhcp: null, dns: null } })).toBe(true);
  });
  it("summarises who serves DHCP and DNS", () => {
    expect(providerSummary({ providers: { dhcp: ref(), dns: ref({ shared: true }) } })).toBe("DNS/DHCP Pi-hole");
    expect(providerSummary({ providers: { dhcp: ref({ kind: "unifi", label: "UniFi" }), dns: ref() } })).toBe("DHCP UniFi · DNS Pi-hole");
    // Two separate Pi-hole connections are two providers, not one shared one.
    expect(providerSummary({ providers: { dhcp: ref(), dns: ref({ shared: false }) } })).toBe("DHCP Pi-hole · DNS Pi-hole");
    expect(providerSummary({ providers: { dhcp: null, dns: null } })).toBe("no network provider");
  });
});
