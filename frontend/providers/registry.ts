import { pihole } from "@/providers/pihole";
import type { ProviderUi } from "@/providers/types";
import { unifi } from "@/providers/unifi";

// One line per provider with its own pages or settings form. A provider missing here still works:
// Settings shows the generic form built from its config schema, and it adds no pages.
export const PROVIDER_UI: Record<string, ProviderUi> = { pihole, unifi };
