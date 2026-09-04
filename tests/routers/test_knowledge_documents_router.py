"""Router tests for /knowledge-documents."""

from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.knowledge_chunk import KnowledgeChunk
from app.models.model_config import ModelConfig
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository


def _create_payload(**overrides):
    base = {
        "title": "GA4 Events",
        "raw_content": (
            "---\ntags: [ecommerce]\nstatus: current\n---\n"
            "# GA4 Events\n\nSome prose about the events table.\n"
        ),
    }
    base.update(overrides)
    return base


@patch(
    "app.commands.knowledge_documents.create_knowledge_document_command.index_knowledge_document_task"
)
def test_create_knowledge_document_splits_frontmatter_and_enqueues_after_commit(
    mock_task, client: TestClient, db: Session
):
    payload = _create_payload()
    r = client.post("/knowledge-documents", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "GA4 Events"
    assert data["content"] == "# GA4 Events\n\nSome prose about the events table.\n"
    assert data["metadata"] == {"tags": ["ecommerce"], "status": "current"}

    # The document must already be committed/queryable by the time .delay() fires.
    mock_task.delay.assert_called_once_with(data["id"])
    repo = KnowledgeDocumentRepository(db)
    assert repo.get_by_id(data["id"]) is not None


@patch(
    "app.commands.knowledge_documents.create_knowledge_document_command.index_knowledge_document_task"
)
def test_create_knowledge_document_malformed_frontmatter_returns_422(
    mock_task, client: TestClient
):
    payload = _create_payload(raw_content="---\ntitle: [unclosed\n---\nbody\n")
    r = client.post("/knowledge-documents", json=payload)
    assert r.status_code == 422
    mock_task.delay.assert_not_called()


@patch(
    "app.commands.knowledge_documents.create_knowledge_document_command.index_knowledge_document_task"
)
def test_create_knowledge_document_rejects_yaml_rce_payload_end_to_end(
    mock_task, client: TestClient, tmp_path
):
    """End-to-end (real HTTP -> router -> command -> frontmatter split) check
    that yaml.safe_load is actually wired in through the full request path,
    not just the isolated frontmatter.py unit test."""
    marker = tmp_path / "pwned"
    payload = _create_payload(
        raw_content=(
            "---\n"
            f"evil: !!python/object/apply:os.system ['touch {marker}']\n"
            "---\nbody\n"
        )
    )
    r = client.post("/knowledge-documents", json=payload)
    assert r.status_code == 422
    mock_task.delay.assert_not_called()
    assert not marker.exists()


@patch(
    "app.commands.knowledge_documents.create_knowledge_document_command.index_knowledge_document_task"
)
def test_get_and_list_knowledge_document(mock_task, client: TestClient):
    created = client.post("/knowledge-documents", json=_create_payload()).json()

    r = client.get(f"/knowledge-documents/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]

    r = client.get("/knowledge-documents")
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()["items"]}
    assert created["id"] in ids


def test_get_knowledge_document_not_found(client: TestClient):
    r = client.get("/knowledge-documents/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


@patch(
    "app.commands.knowledge_documents.create_knowledge_document_command.index_knowledge_document_task"
)
def test_chunk_count_reflects_actual_chunk_rows(
    mock_task, client: TestClient, db: Session
):
    created = client.post("/knowledge-documents", json=_create_payload()).json()
    assert created["chunk_count"] == 0

    embedding_config = ModelConfig(
        slug=f"embed-{uuid4().hex[:8]}",
        name="Embedding Config",
        provider="openai",
        model="text-embedding-3-small",
        config_type="embedding",
        params={"chunk_size": 300, "chunk_overlap": 0, "strategy": "fixed_size"},
    )
    db.add(embedding_config)
    db.commit()
    for i in range(3):
        db.add(
            KnowledgeChunk(
                document_id=created["id"],
                chunk_index=i,
                content=f"chunk {i}",
                embedding=[0.1, 0.2],
                embedding_config_id=embedding_config.id,
                chunk_params={},
            )
        )
    db.commit()

    detail = client.get(f"/knowledge-documents/{created['id']}").json()
    assert detail["chunk_count"] == 3

    listed = client.get("/knowledge-documents").json()
    item = next(item for item in listed["items"] if item["id"] == created["id"])
    assert item["chunk_count"] == 3


@patch(
    "app.commands.knowledge_documents.update_knowledge_document_command.index_knowledge_document_task"
)
@patch(
    "app.commands.knowledge_documents.create_knowledge_document_command.index_knowledge_document_task"
)
def test_update_with_new_content_enqueues_reindex(
    mock_create_task, mock_update_task, client: TestClient
):
    created = client.post("/knowledge-documents", json=_create_payload()).json()
    mock_update_task.reset_mock()

    r = client.put(
        f"/knowledge-documents/{created['id']}",
        json={"raw_content": "# New body\n\nUpdated prose.\n"},
    )
    assert r.status_code == 200
    assert r.json()["content"] == "# New body\n\nUpdated prose.\n"
    mock_update_task.delay.assert_called_once_with(created["id"])


@patch(
    "app.commands.knowledge_documents.update_knowledge_document_command.index_knowledge_document_task"
)
@patch(
    "app.commands.knowledge_documents.create_knowledge_document_command.index_knowledge_document_task"
)
def test_title_only_update_does_not_enqueue_reindex(
    mock_create_task, mock_update_task, client: TestClient
):
    created = client.post("/knowledge-documents", json=_create_payload()).json()
    mock_update_task.reset_mock()

    r = client.put(f"/knowledge-documents/{created['id']}", json={"title": "Renamed"})
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"
    assert r.json()["content"] == created["content"]
    mock_update_task.delay.assert_not_called()


@patch(
    "app.commands.knowledge_documents.create_knowledge_document_command.index_knowledge_document_task"
)
def test_delete_knowledge_document_hard_deletes(mock_task, client: TestClient):
    created = client.post("/knowledge-documents", json=_create_payload()).json()

    r = client.delete(f"/knowledge-documents/{created['id']}")
    assert r.status_code == 204

    r = client.get(f"/knowledge-documents/{created['id']}")
    assert r.status_code == 404
