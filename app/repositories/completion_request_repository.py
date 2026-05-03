from typing import Optional
from uuid import UUID
from sqlalchemy import Select, select
from sqlalchemy.orm import Session
from app.models.completion_request import CompletionRequest


class CompletionRequestRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: dict) -> CompletionRequest:
        record = CompletionRequest(**data)
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
