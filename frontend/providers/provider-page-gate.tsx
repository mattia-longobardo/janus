"use client";

import type { ReactNode } from "react";

import { Notice } from "@/components/ui";
import { useFeatures } from "@/lib/features";
import { providerNav } from "@/lib/provider-status";

// A provider page opens only while the menu would list it: the provider holds the page's role and offers its
// capability there. A Pi-hole kept for DNS next to another DHCP provider has no cutover page.
export function ProviderPageGate({ href, children }: { href: string; children: ReactNode }) {
  const { features } = useFeatures();
  if (features === null) return <p className="text-sm text-muted">Loading…</p>;
  if (!providerNav(features).some((item) => item.href === href)) {
    return <Notice>This page is not available with the current network provider.</Notice>;
  }
  return <>{children}</>;
}
