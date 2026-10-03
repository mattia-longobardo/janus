# Provider UI

A provider needs no frontend code: Settings builds its config form from the pydantic JSON schema
(`generic-config-form.tsx`; fields in `secret_fields` become write-only password inputs).

For dedicated pages add `frontend/providers/<kind>/index.ts` exporting a `ProviderUi` (see `types.ts`) and one line in
`registry.ts`. Pages are served at `/integrations/<kind>/<slug>`. Each `ProviderPage` declares the `role` it needs and,
optionally, a `capability`: it is listed (and opened, via `ProviderPageGate`) only while the provider holds that role
and offers that capability in it. Full guide: `docs/providers/adding-a-provider.md`.
