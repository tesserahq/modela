from pydantic import BaseModel, Field
from typing import Any, Optional
from uuid import UUID
from datetime import datetime
from decimal import Decimal

from app.schemas.user import UserCompact


class CompletionRequestCreate(BaseModel):
    request_id: str
    project_id: str
    model_config_slug: Optional[str] = None
    provider: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    cost_estimate_usd: Decimal = Decimal("0")
    finish_reason: Optional[str] = None
    created_by_id: Optional[UUID] = None


class CompletionRequestResponse(BaseModel):
    id: UUID
    request_id: str
    project_id: str
    model_config_slug: Optional[str] = None
    provider: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    cost_estimate_usd: Decimal
    finish_reason: Optional[str] = None
    created_by_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CostSummaryItem(BaseModel):
    group_key: str
    group_value: Any
    total_cost_usd: Decimal
    group_details: UserCompact | None = Field(
        default=None,
        description=(
            "Populated when group_key is 'user' and group_value is a known user id; "
            "null for unattributed rows, missing users, and non-user dimensions."
        ),
    )
