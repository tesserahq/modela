from datetime import date
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.rbac import build_rbac_dependencies, infer_domain
from app.db import get_db
from app.repositories.completion_request_repository import CompletionRequestRepository
from app.schemas.completion_request import CostSummaryItem
from app.services.cost_analytics import attach_group_details
from tessera_sdk.server.dependencies.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])
RBAC_RESOURCE = "completion_request"
_rbac = build_rbac_dependencies(resource=RBAC_RESOURCE, domain_resolver=infer_domain)

GroupByDimension = Literal["user", "provider", "model", "project_id"]


@router.get(
    "/costs",
    response_model=list[CostSummaryItem],
    dependencies=[Depends(_rbac["read"]), Depends(get_current_user)],
)
def get_cost_summary(
    group_by: GroupByDimension = Query(...),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    project_id: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    created_by_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = CompletionRequestRepository(db).cost_summary_query(
        group_by=group_by,
        start_date=start_date,
        end_date=end_date,
        project_id=project_id,
        provider=provider,
        model=model,
        created_by_id=created_by_id,
        limit=limit,
    )
    rows = db.execute(query).all()
    items = [
        CostSummaryItem(
            group_key=group_by,
            group_value=row.group_value,
            total_cost_usd=row.total_cost_usd or 0,
        )
        for row in rows
    ]
    return attach_group_details(group_by, items, db)
