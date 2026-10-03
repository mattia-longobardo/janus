# Network providers

A provider is a folder here that exports `SPEC` (a `ProviderSpec`); `registry.discover()` finds it by itself.
Folders starting with `_` are skipped (`_template/` is the copyable skeleton).

1. `cp -r _template <kind>` and rename `template`/`Template` (imports included).
2. Fill `SPEC` in `__init__.py`: roles, capabilities, policies, config model, secret fields.
3. Implement the methods the declared capabilities require (`provider.py`, `client.py`).
4. Test with respx; `scripts/test.sh tests/providers` also runs the contract tests against your provider.
5. Optional: pages in `frontend/providers/<kind>/` plus one line in `frontend/providers/registry.ts`.

A provider never imports another provider; code outside `app/providers/` never imports `app.providers.<kind>`.

Full guide: [docs/providers/adding-a-provider.md](../../../docs/providers/adding-a-provider.md)
