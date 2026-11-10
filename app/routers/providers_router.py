from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy import select
from tessera_sdk.server.dependencies.auth import get_current_user

from app.auth.rbac import build_rbac_dependencies
from app.db import DbSession
from app.exceptions.resource_not_found_error import ResourceNotFoundError
from app.inference.adapters.base import BaseProviderAdapter
from app.inference.adapters.registry import PROVIDER_REGISTRY
from app.models.provider_model_catalog import ProviderModelCatalogEntry
from app.schemas.provider import (
    ProviderCatalogChangeRead,
    ProviderCatalogChangeReview,
    ProviderCatalogCheckResponse,
    ProviderModelSchema,
    ProviderSchema,
)
from app.services.pricing import get_model_pricing
from app.services.provider_catalog_history import (
    clear_review,
    find_entry,
    mark_reviewed,
)
from app.tasks.check_provider_model_catalog import check_provider_model_catalog_task

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
            embedding_models=[
                _with_pricing(adapter, m) for m in adapter.list_embedding_models()
            ],
            parameters=adapter.parameters,
        )
        for adapter in PROVIDER_REGISTRY.values()
    ]


@router.post(
    "/check-catalog",
    response_model=ProviderCatalogCheckResponse,
    status_code=202,
)
def check_provider_catalog(
    _authorized: bool = Depends(rbac["update"]),
    _current_user=Depends(get_current_user),
) -> ProviderCatalogCheckResponse:
    """Manually trigger the provider model catalog drift check (normally weekly)."""
    result = check_provider_model_catalog_task.delay()
    return ProviderCatalogCheckResponse(task_id=result.id)


@router.get("/catalog-changes", response_model=Page[ProviderCatalogChangeRead])
def list_catalog_changes(
    db: DbSession,
    provider_id: str | None = None,
    kind: str | None = None,
    reviewed: bool | None = None,
    _authorized: bool = Depends(rbac["read"]),
    _current_user=Depends(get_current_user),
):
    """Model catalog changes and failed checks, newest first (PRD 0023)."""
    query = select(ProviderModelCatalogEntry)
    if provider_id is not None:
        query = query.where(ProviderModelCatalogEntry.provider_id == provider_id)
    if kind is not None:
        query = query.where(ProviderModelCatalogEntry.kind == kind)
    if reviewed is True:
        query = query.where(ProviderModelCatalogEntry.reviewed_at.is_not(None))
    elif reviewed is False:
        query = query.where(ProviderModelCatalogEntry.reviewed_at.is_(None))
    query = query.order_by(
        ProviderModelCatalogEntry.detected_at.desc(),
        ProviderModelCatalogEntry.id,
    )
    return paginate(db, query)


@router.patch(
    "/catalog-changes/{entry_id}",
    response_model=ProviderCatalogChangeRead,
)
def review_catalog_change(
    entry_id: UUID,
    body: ProviderCatalogChangeReview,
    db: DbSession,
    _authorized: bool = Depends(rbac["update"]),
    current_user=Depends(get_current_user),
) -> ProviderModelCatalogEntry:
    """Mark a change as reviewed by the signed-in user, or clear the review."""
    entry = find_entry(db, entry_id)
    if entry is None:
        raise ResourceNotFoundError(f"Catalog change {entry_id} not found")
    if body.reviewed:
        mark_reviewed(db, entry, current_user.id)
    else:
        clear_review(db, entry)
    return entry
