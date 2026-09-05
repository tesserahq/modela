"""Knowledge base documents API: CRUD for the product-wide knowledge base."""

from fastapi import APIRouter, Depends, Request
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy.orm import Session
from tessera_sdk.server.dependencies.auth import (
    get_current_user,  # type: ignore[import-untyped]
)

from app.auth.rbac import build_rbac_dependencies
from app.commands.knowledge_documents import (
    CreateKnowledgeDocumentCommand,
    DeleteKnowledgeDocumentCommand,
    UpdateKnowledgeDocumentCommand,
)
from app.db import get_db
from app.models.knowledge_document import KnowledgeDocument
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.routers.utils.dependencies import get_knowledge_document_by_id
from app.schemas.knowledge_document import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentRead,
    KnowledgeDocumentUpdate,
)

router = APIRouter(
    prefix="/knowledge-documents",
    tags=["knowledge-documents"],
    responses={404: {"description": "Not found"}},
)


async def infer_domain(request: Request) -> str | None:
    # The knowledge base is product-wide, not project-scoped — same "global
    # domain" pattern used by mcp_servers.
    return "*"


RESOURCE_KNOWLEDGE_DOCUMENTS = "knowledge_document"
rbac = build_rbac_dependencies(
    resource=RESOURCE_KNOWLEDGE_DOCUMENTS,
    domain_resolver=infer_domain,
)


@router.get("", response_model=Page[KnowledgeDocumentRead])
def list_knowledge_documents(
    _authorized: bool = Depends(rbac["read"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[KnowledgeDocumentRead]:
    """List all knowledge documents with pagination."""
    repo = KnowledgeDocumentRepository(db)
    return paginate(db, repo.list_query())


@router.post("", response_model=KnowledgeDocumentRead, status_code=201)
def create_knowledge_document(
    data: KnowledgeDocumentCreate,
    _authorized: bool = Depends(rbac["create"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentRead:
    """Create a knowledge document. Chunking/embedding is enqueued asynchronously."""
    command = CreateKnowledgeDocumentCommand(db)
    return command.execute(data)


@router.get("/{id}", response_model=KnowledgeDocumentRead)
def get_knowledge_document(
    document: KnowledgeDocument = Depends(get_knowledge_document_by_id),
    _authorized: bool = Depends(rbac["read"]),
    _current_user=Depends(get_current_user),
) -> KnowledgeDocumentRead:
    """Get a knowledge document by ID."""
    return document


@router.put("/{id}", response_model=KnowledgeDocumentRead)
def update_knowledge_document(
    data: KnowledgeDocumentUpdate,
    document: KnowledgeDocument = Depends(get_knowledge_document_by_id),
    _authorized: bool = Depends(rbac["update"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentRead:
    """Update a knowledge document. Re-indexing is enqueued only when content changed."""
    command = UpdateKnowledgeDocumentCommand(db)
    return command.execute(document, data)


@router.delete("/{id}", status_code=204)
def delete_knowledge_document(
    document: KnowledgeDocument = Depends(get_knowledge_document_by_id),
    _authorized: bool = Depends(rbac["delete"]),
    _current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Hard-delete a knowledge document and its chunks (synchronous)."""
    command = DeleteKnowledgeDocumentCommand(db)
    command.execute(document)
