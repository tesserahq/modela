from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.knowledge_chunk import KnowledgeChunk
from app.models.model_config import ModelConfig
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.tasks.index_knowledge_document import index_knowledge_document_task


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


def _chunks_for(db, document_id):
    return (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.document_id == document_id)
        .order_by(KnowledgeChunk.chunk_index)
        .all()
    )


@contextmanager
def _run_task_against(db, adapter=None):
    """The task opens/closes its own SessionLocal(); redirect that to the
    shared test session (so writes are visible within this test's
    transaction), and no-op its db.close() so it doesn't tear down the
    fixture's session/connection out from under the rest of the test."""
    patches = [
        patch("app.tasks.index_knowledge_document.SessionLocal", return_value=db),
        patch.object(db, "close"),
    ]
    if adapter is not None:
        patches.append(
            patch(
                "app.tasks.index_knowledge_document.get_adapter", return_value=adapter
            )
        )
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


def test_creates_chunks_tagged_with_embedding_config(db):
    embedding_config = _make_embedding_config(db)
    document = KnowledgeDocumentRepository(db).create(
        title="Doc", content="a" * 650, metadata={}
    )

    fake_adapter = MagicMock()
    fake_adapter.create_embeddings.return_value = [[0.1, 0.2]] * 3

    with _run_task_against(db, adapter=fake_adapter):
        index_knowledge_document_task(str(document.id))

    chunks = _chunks_for(db, document.id)
    assert len(chunks) == 3
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert all(c.embedding_config_id == embedding_config.id for c in chunks)
    assert all(
        c.chunk_params
        == {"chunk_size": 300, "chunk_overlap": 0, "strategy": "fixed_size"}
        for c in chunks
    )
    fake_adapter.create_embeddings.assert_called_once()
    call_args = fake_adapter.create_embeddings.call_args
    assert call_args.args[0] == "text-embedding-3-small"
    assert len(call_args.args[1]) == 3  # batched in a single call


def test_reindex_deletes_old_chunks_first(db):
    _make_embedding_config(db)
    document = KnowledgeDocumentRepository(db).create(
        title="Doc", content="a" * 350, metadata={}
    )
    fake_adapter = MagicMock()
    fake_adapter.create_embeddings.return_value = [[0.1, 0.2]] * 2

    with _run_task_against(db, adapter=fake_adapter):
        index_knowledge_document_task(str(document.id))
        assert len(_chunks_for(db, document.id)) == 2

        # Reindex with different (shorter) content -> fewer chunks.
        document.content = "a" * 100
        db.commit()
        fake_adapter.create_embeddings.return_value = [[0.1, 0.2]]
        index_knowledge_document_task(str(document.id))

    chunks = _chunks_for(db, document.id)
    assert len(chunks) == 1


def test_raises_when_no_default_embedding_config_exists(db):
    document = KnowledgeDocumentRepository(db).create(
        title="Doc", content="hello world", metadata={}
    )

    with _run_task_against(db), pytest.raises(RuntimeError):
        index_knowledge_document_task(str(document.id))


def test_deleted_document_is_a_noop(db):
    with _run_task_against(db):
        index_knowledge_document_task(str(uuid4()))
