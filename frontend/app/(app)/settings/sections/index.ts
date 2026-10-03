import type { ComponentType } from "react";

import type { Features } from "@/lib/types";

import { GuestsSection } from "./guests";
import { IntegrationsSection } from "./integrations";
import { ProvidersSection } from "./providers";
import { SignInSection } from "./sign-in";

export type SettingsSection = {
  id: string;
  title: string;
  Component: ComponentType;
  requires?: (f: Features) => boolean;
};

// One line per self-contained settings card (each loads and saves on its own).
export const EXTRA_SECTIONS: SettingsSection[] = [
  { id: "providers", title: "Network providers", Component: ProvidersSection },
  { id: "integrations", title: "Integrations", Component: IntegrationsSection },
  { id: "guests", title: "Guests", Component: GuestsSection, requires: (f) => Boolean(f.guests?.enabled) },
  { id: "sign-in", title: "Sign-in & users", Component: SignInSection },
];
