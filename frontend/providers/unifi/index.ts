import { Wifi } from "lucide-react";

import type { ProviderUi } from "@/providers/types";

import { ClientsPage } from "./clients-page";

export const unifi: ProviderUi = {
  kind: "unifi",
  pages: [{ slug: "clients", label: "UniFi clients", icon: Wifi, Component: ClientsPage, role: "dhcp", capability: "client_inventory" }],
};
