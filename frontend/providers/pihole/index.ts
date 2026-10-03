import { Router } from "lucide-react";

import type { ProviderUi } from "@/providers/types";

import { CutoverPage } from "./cutover-page";

export const pihole: ProviderUi = {
  kind: "pihole",
  pages: [{ slug: "cutover", label: "DHCP cutover", icon: Router, Component: CutoverPage, role: "dhcp", capability: "dhcp_server" }],
};
