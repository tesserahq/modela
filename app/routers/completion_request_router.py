from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth.rbac import build_rbac_dependencies, infer_domain
from app.models.completion_request import CompletionRequest
from app.repositories.completion_request_repository import CompletionRequestRepository
from app.routers.utils.dependencies import get_completion_request_by_id
from app.schemas.completion_request import CompletionRequestResponse
from tessera_sdk.server.dependencies.auth import get_current_user

router = APIRouter(prefix="/completion-requests", tags=["completion-requests"])
RBAC_RESOURCE = "completion_request"
_rbac = build_rbac_dependencies(resource=RBAC_RESOURCE, domain_resolver=infer_domain)


@router.get(
    "",
    response_model=Page[CompletionRequestResponse],
    dependencies=[Depends(_rbac["read"]), Depends(get_current_user)],
)
def list_completion_requests(
    project_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = CompletionRequestRepository(db).list_query(project_id=project_id)
    return paginate(db, query)


@router.get(
    "/{id}",
    response_model=CompletionRequestResponse,
    dependencies=[Depends(_rbac["read"]), Depends(get_current_user)],
)
def get_completion_request(
    record: CompletionRequest = Depends(get_completion_request_by_id),
):
    return CompletionRequestResponse.model_validate(record)
