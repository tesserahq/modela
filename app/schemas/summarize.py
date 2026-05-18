from typing import Optional
from pydantic import BaseModel


class SummarizeTextRequest(BaseModel):
    content: str
    model: Optional[str] = None


class SummarizeFileRequest(BaseModel):
    file_url: str
    mime_type: str = "application/pdf"
    model: Optional[str] = None


class SummarizeResponse(BaseModel):
    summary: str
    model: str
    request_id: str
