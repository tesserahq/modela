from datetime import date, timedelta, datetime, timezone
from typing import Optional
from uuid import UUID
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session
from app.models.completion_request import CompletionRequest
from app.schemas.completion_request import CompletionRequestCreate


class CompletionRequestRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: CompletionRequestCreate) -> CompletionRequest:
        record = CompletionRequest(**data.model_dump())
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_by_id(self, id: UUID) -> Optional[CompletionRequest]:
        return (
            self.db.query(CompletionRequest).filter(CompletionRequest.id == id).first()
        )

    def list_query(self, project_id: Optional[str] = None) -> Select:
        query = select(CompletionRequest)
        if project_id is not None:
            query = query.filter(CompletionRequest.project_id == project_id)
        return query.order_by(CompletionRequest.created_at.desc())

    _GROUP_BY_COLUMNS = {
        "user": CompletionRequest.created_by_id,
        "provider": CompletionRequest.provider,
        "model": CompletionRequest.model,
        "project_id": CompletionRequest.project_id,
    }

    def cost_summary_query(
        self,
        group_by: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        project_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        created_by_id: Optional[UUID] = None,
        limit: int = 10,
    ) -> Select:
        group_col = self._GROUP_BY_COLUMNS[group_by]
        total = func.sum(CompletionRequest.cost_estimate_usd).label("total_cost_usd")
        query = select(group_col.label("group_value"), total)

        if start_date is not None:
            query = query.filter(
                CompletionRequest.created_at
                >= datetime(
                    start_date.year,
                    start_date.month,
                    start_date.day,
                    tzinfo=timezone.utc,
                )
            )
        if end_date is not None:
            cutoff = end_date + timedelta(days=1)
            query = query.filter(
                CompletionRequest.created_at
                < datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=timezone.utc)
            )
        if project_id is not None:
            query = query.filter(CompletionRequest.project_id == project_id)
        if provider is not None:
            query = query.filter(CompletionRequest.provider == provider)
        if model is not None:
            query = query.filter(CompletionRequest.model == model)
        if created_by_id is not None:
            query = query.filter(CompletionRequest.created_by_id == created_by_id)

        return query.group_by(group_col).order_by(total.desc()).limit(limit)
