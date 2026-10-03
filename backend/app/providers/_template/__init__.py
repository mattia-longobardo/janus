"""Copyable skeleton of a network provider; see docs/providers/adding-a-provider.md.

The leading underscore keeps it out of discovery. Copy this folder to `app/providers/<kind>/`, rename
`template`/`Template` everywhere, fill the TODO(provider-author) spots and `SPEC` becomes live on the next start.
"""
from app.providers._template.client import TemplateClient
from app.providers._template.provider import KIND, POLICIES, TemplateConfig, TemplateProvider
from app.providers.base import Capability, ProviderSpec, Role


def open_provider(cfg: TemplateConfig) -> TemplateProvider:
    return TemplateProvider(TemplateClient(cfg.url, cfg.token), cfg)


SPEC = ProviderSpec(
    kind=KIND,                                   # must equal the folder name
    label="Template router",
    description="One line shown in Settings under the provider picker.",
    roles=frozenset({Role.DHCP}),                # add Role.DNS only together with a DNS capability
    capabilities=frozenset({Capability.RESERVATIONS}),
    policies=POLICIES,                           # required whenever RESERVATIONS is declared
    config_model=TemplateConfig,
    provider_class=TemplateProvider,
    secret_fields=frozenset({"token"}),
    # env_defaults=lambda: {"url": settings.template_url, "token": settings.template_token},   # add the fields to app/config.py
    open=open_provider,
)
