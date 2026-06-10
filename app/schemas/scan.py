from typing import Any, Optional
from pydantic import BaseModel


class ScanFileRequest(BaseModel):
    file_url: str
    mime_type: str = "application/pdf"
    model: Optional[str] = None


class ScanResponse(BaseModel):
    data: dict[str, Any]
    model: str
    request_id: str
