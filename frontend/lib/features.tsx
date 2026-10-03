"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { Features } from "@/lib/types";
import { useResource } from "@/lib/use-resource";

const FeaturesContext = createContext<{ features: Features | null; reload: () => Promise<void> }>({
  features: null,
  reload: async () => {},
});

export function FeaturesProvider({ children }: { children: ReactNode }) {
  const { data, reload } = useResource<Features>("/features", { refreshMs: 30_000 });
  return <FeaturesContext.Provider value={{ features: data ?? null, reload }}>{children}</FeaturesContext.Provider>;
}

export function useFeatures() {
  return useContext(FeaturesContext);
}
