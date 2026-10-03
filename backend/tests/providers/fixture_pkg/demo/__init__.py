from contextlib import nullcontext

from pydantic import BaseModel

from app.providers.base import Capability, Policy, ProviderSpec, Role


class DemoConfig(BaseModel):
    url: str = ""


SPEC = ProviderSpec(kind="demo", label="Demo router", roles=frozenset({Role.DHCP}),
                    capabilities=frozenset({Capability.RESERVATIONS}), config_model=DemoConfig,
                    open=lambda cfg: nullcontext(object()), policies=frozenset({Policy.FULL}))
