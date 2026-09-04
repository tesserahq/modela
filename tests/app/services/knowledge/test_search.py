from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.model_config import ModelConfig
from app.services.knowledge.search import search_knowledge_base_chunks


def _make_embedding_config(db, **overrides):
    config = ModelConfig(
        slug=f"embed-{uuid4().hex[:8]}",
        name="Embedding Config",
        provider="openai",
        model="text-embedding-3-small",
        config_type="embedding",
        is_default=True,
        params={"chunk_size": 300, "chunk_overlap": 0, "strategy": "fixed_size"},
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _make_document(db, **metadata):
    doc = KnowledgeDocument(title="Doc", content="body", extended_info=metadata or None)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _make_chunk(db, document, embedding_config, content, vector):
    chunk = KnowledgeChunk(
        document_id=document.id,
        chunk_index=0,
        content=content,
        embedding=vector,
        embedding_config_id=embedding_config.id,
        chunk_params={},
    )
    db.add(chunk)
    db.commit()
    return chunk


def _mock_adapter(query_vector):
    adapter = MagicMock()
    adapter.create_embeddings.return_value = [query_vector]
    return adapter


def test_returns_closest_chunks_by_cosine_distance(db):
    embedding_config = _make_embedding_config(db)
    doc = _make_document(db)
    _make_chunk(db, doc, embedding_config, "far", [1.0, 0.0])
    _make_chunk(db, doc, embedding_config, "close", [0.0, 1.0])

    with patch(
        "app.services.knowledge.search.get_adapter",
        return_value=_mock_adapter([0.0, 1.0]),
    ):
        results = search_knowledge_base_chunks(db, "query", top_k=1)

    assert results == ["close"]


def test_scoped_to_active_embedding_config(db):
    active_config = _make_embedding_config(db)
    other_config = _make_embedding_config(db, is_default=False)
    doc = _make_document(db)
    # "closer" chunk belongs to a different (non-active) embedding config —
    # must never be returned, even though it'd rank first by raw distance.
    _make_chunk(db, doc, other_config, "wrong config", [0.0, 1.0])
    _make_chunk(db, doc, active_config, "right config", [1.0, 0.0])

    with patch(
        "app.services.knowledge.search.get_adapter",
        return_value=_mock_adapter([0.0, 1.0]),
    ):
        results = search_knowledge_base_chunks(db, "query")

    assert results == ["right config"]


def test_excludes_stale_status_documents(db):
    embedding_config = _make_embedding_config(db)
    fresh_doc = _make_document(db)
    stale_doc = _make_document(db, status="stale")
    _make_chunk(db, fresh_doc, embedding_config, "fresh", [1.0, 0.0])
    _make_chunk(db, stale_doc, embedding_config, "stale", [1.0, 0.0])

    with patch(
        "app.services.knowledge.search.get_adapter",
        return_value=_mock_adapter([1.0, 0.0]),
    ):
        results = search_knowledge_base_chunks(db, "query")

    assert results == ["fresh"]


def test_excludes_past_stale_after_documents(db):
    embedding_config = _make_embedding_config(db)
    fresh_doc = _make_document(db)
    expired_doc = _make_document(
        db, stale_after=(datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    )
    _make_chunk(db, fresh_doc, embedding_config, "fresh", [1.0, 0.0])
    _make_chunk(db, expired_doc, embedding_config, "expired", [1.0, 0.0])

    with patch(
        "app.services.knowledge.search.get_adapter",
        return_value=_mock_adapter([1.0, 0.0]),
    ):
        results = search_knowledge_base_chunks(db, "query")

    assert results == ["fresh"]


def test_no_default_embedding_config_returns_empty(db):
    results = search_knowledge_base_chunks(db, "query")
    assert results == []


def test_no_documents_indexed_returns_empty(db):
    _make_embedding_config(db)
    with patch(
        "app.services.knowledge.search.get_adapter",
        return_value=_mock_adapter([1.0, 0.0]),
    ):
        results = search_knowledge_base_chunks(db, "query")
    assert results == []
