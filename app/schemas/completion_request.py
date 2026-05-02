from pydantic import BaseModel
from typing import Optional, Any
from uuid import UUID
from datetime import datetime
from decimal import Decimal


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
