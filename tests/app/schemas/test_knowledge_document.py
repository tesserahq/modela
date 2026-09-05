import pytest
from pydantic import ValidationError

from app.schemas.knowledge_document import (
    MAX_RAW_CONTENT_BYTES,
    KnowledgeDocumentCreate,
    KnowledgeDocumentUpdate,
)


@pytest.mark.parametrize("schema", [KnowledgeDocumentCreate, KnowledgeDocumentUpdate])
def test_raw_content_limit_is_enforced_in_utf8_bytes(schema):
    content = "😀" * (MAX_RAW_CONTENT_BYTES // 4 + 1)
    payload = {"raw_content": content}
    if schema is KnowledgeDocumentCreate:
        payload["title"] = "Oversized"

    with pytest.raises(ValidationError, match="1 MiB"):
        schema.model_validate(payload)
