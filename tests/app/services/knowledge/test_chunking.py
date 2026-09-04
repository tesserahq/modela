import pytest

from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.services.knowledge.chunking import chunk_text


def test_fixed_size_chunking_respects_size_and_overlap():
    content = "a" * 100
    chunks = chunk_text(content, chunk_size=30, chunk_overlap=10, strategy="fixed_size")
    assert chunks[0] == content[0:30]
    assert chunks[1] == content[20:50]
    assert all(len(c) <= 30 for c in chunks)


def test_empty_content_produces_no_chunks():
    assert chunk_text("", chunk_size=100, chunk_overlap=0, strategy="fixed_size") == []


def test_unknown_strategy_is_rejected():
    with pytest.raises(InvalidParameterError):
        chunk_text("hello", chunk_size=10, chunk_overlap=0, strategy="semantic")


def test_chunk_count_cap_is_enforced():
    content = "a" * 2000
    with pytest.raises(InvalidParameterError):
        chunk_text(content, chunk_size=1, chunk_overlap=0, strategy="fixed_size")
