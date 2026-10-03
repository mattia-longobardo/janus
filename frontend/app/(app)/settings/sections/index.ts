import type { ComponentType } from "react";

import type { Features } from "@/lib/types";

import { IntegrationsSection } from "./integrations";
import { SignInSection } from "./sign-in";

export type SettingsSection = {
  id: string;
  title: string;
  Component: ComponentType;
  requires?: (f: Features) => boolean;
};

// One line per self-contained settings card (each loads and saves on its own).
export const EXTRA_SECTIONS: SettingsSection[] = [
  { id: "integrations", title: "Integrations", Component: IntegrationsSection },
  { id: "sign-in", title: "Sign-in & users", Component: SignInSection },
];
