import type { LucideIcon } from "lucide-react";
import type { ComponentType } from "react";

export type JsonSchemaProperty = {
  type?: string;
  title?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  format?: string;
  anyOf?: { type?: string; enum?: string[] }[];   // Pydantic writes `X | None` fields this way
};
export type JsonSchema = { properties: Record<string, JsonSchemaProperty>; required?: string[] };

// A page is listed only while its provider holds `role` and, when set, offers `capability` in that role.
export type ProviderPage = { slug: string; label: string; icon: LucideIcon; Component: ComponentType; role: "dhcp" | "dns"; capability?: string };

export type ProviderUi = {
  kind: string; // == backend folder name
  pages: ProviderPage[]; // shown at /integrations/<kind>/<slug> and in the sidebar
  SettingsForm?: ComponentType<ConfigFormProps>; // optional: the generic form covers most providers
};

export type ConfigFormProps = {
  schema: JsonSchema;
  secretFields: string[];
  value: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
};
