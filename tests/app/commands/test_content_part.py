import pytest
from pydantic_ai.messages import DocumentUrl, ImageUrl

from app.commands.scan.create_scan_command import (
    _make_content_part as scan_make_content_part,
)
from app.commands.summarize.create_summarize_command import (
    _make_content_part as summarize_make_content_part,
)


@pytest.mark.parametrize(
    "make_content_part", [scan_make_content_part, summarize_make_content_part]
)
class TestMakeContentPart:
    @pytest.mark.parametrize(
        "mime_type", ["image/jpeg", "image/png", "image/gif", "image/webp"]
    )
    def test_image_types_return_image_url(self, make_content_part, mime_type):
        result = make_content_part("https://example.com/file", mime_type)
        assert isinstance(result, ImageUrl)
        assert result.url == "https://example.com/file"
        assert result.media_type == mime_type

    @pytest.mark.parametrize("mime_type", ["application/pdf", "text/plain"])
    def test_document_types_return_document_url(self, make_content_part, mime_type):
        result = make_content_part("https://example.com/file", mime_type)
        assert isinstance(result, DocumentUrl)
        assert result.url == "https://example.com/file"
        assert result.media_type == mime_type
