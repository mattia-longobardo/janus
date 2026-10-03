import type { ComponentType } from "react";

import type { Features } from "@/lib/types";

export type SettingsSection = {
  id: string;
  title: string;
  Component: ComponentType;
  requires?: (f: Features) => boolean;
};

// One line per self-contained settings card (each loads and saves on its own).
export const EXTRA_SECTIONS: SettingsSection[] = [];
