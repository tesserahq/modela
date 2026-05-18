import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.rbac import build_rbac_dependencies, infer_project
from app.commands.summarize.create_summarize_command import CreateSummarizeCommand
from app.db import get_db
from app.schemas.summarize import (
    SummarizeFileRequest,
    SummarizeResponse,
    SummarizeTextRequest,
)
from tessera_sdk.server.dependencies.auth import get_current_user

router = APIRouter(tags=["summarize"])
RBAC_RESOURCE = "completion"
_rbac = build_rbac_dependencies(resource=RBAC_RESOURCE, project_resolver=infer_project)


@router.post(
    "/summarize/text",
    response_model=SummarizeResponse,
    dependencies=[Depends(_rbac["create"])],
)
async def summarize_text(
    payload: SummarizeTextRequest,
    project_id: str = Depends(infer_project),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    request_id = str(uuid.uuid4())
    return await CreateSummarizeCommand(db).execute_text(
        content=payload.content,
        model_slug=payload.model,
        project_id=project_id,
        request_id=request_id,
        user_id=current_user.id,
    )


@router.post(
    "/summarize/file",
    response_model=SummarizeResponse,
    dependencies=[Depends(_rbac["create"])],
)
async def summarize_file(
    payload: SummarizeFileRequest,
    project_id: str = Depends(infer_project),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    request_id = str(uuid.uuid4())
    return await CreateSummarizeCommand(db).execute_file(
        file_url=payload.file_url,
        mime_type=payload.mime_type,
        model_slug=payload.model,
        project_id=project_id,
        request_id=request_id,
        user_id=current_user.id,
    )
