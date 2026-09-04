from fastapi import APIRouter, Depends, Request
from tessera_sdk.server.dependencies.auth import get_current_user

from app.auth.rbac import build_rbac_dependencies
from app.inference.adapters.base import BaseProviderAdapter
from app.inference.adapters.registry import PROVIDER_REGISTRY
from app.schemas.provider import ProviderModelSchema, ProviderSchema
from app.services.pricing import get_model_pricing

router = APIRouter(
    prefix="/providers",
    tags=["providers"],
    responses={404: {"description": "Not found"}},
)


async def infer_domain(request: Request) -> str | None:
    return "*"


RESOURCE = "provider"
rbac = build_rbac_dependencies(
    resource=RESOURCE,
    domain_resolver=infer_domain,
)


def _with_pricing(
    adapter: BaseProviderAdapter, model: ProviderModelSchema
) -> ProviderModelSchema:
    input_price, output_price = get_model_pricing(adapter.provider_id, model.id)
    return model.model_copy(
        update={
            "input_price_per_mtok": input_price,
            "output_price_per_mtok": output_price,
        }
    )


@router.get("", response_model=list[ProviderSchema])
def list_providers(
    _authorized: bool = Depends(rbac["read"]),
    _current_user=Depends(get_current_user),
) -> list[ProviderSchema]:
    """List available providers and their supported models."""
    return [
        ProviderSchema(
            id=adapter.provider_id,
            name=adapter.provider_name,
            models=[_with_pricing(adapter, m) for m in adapter.list_models()],
            parameters=adapter.parameters,
        )
        for adapter in PROVIDER_REGISTRY.values()
    ]
