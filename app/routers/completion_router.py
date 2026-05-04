import uuid
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.rbac import build_rbac_dependencies, infer_project
from app.commands.completions.create_completion_command import CreateCompletionCommand
from app.db import get_db
from app.schemas.completion import CompletionCreate, CompletionResponse
from tessera_sdk.server.dependencies.auth import get_current_user

router = APIRouter(tags=["completions"])
RBAC_RESOURCE = "completion"
_rbac = build_rbac_dependencies(resource=RBAC_RESOURCE, project_resolver=infer_project)


@router.post(
    "/chat/completions",
    response_model=CompletionResponse,
    dependencies=[Depends(_rbac["create"])],
)
async def create_completion(
    payload: CompletionCreate,
    response: Response,
    project_id: str = Depends(infer_project),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    request_id = str(uuid.uuid4())
    result = await CreateCompletionCommand(db).execute(
        payload, project_id, request_id, user_id=current_user.id
    )
    response.headers["X-Modela-Config-Slug"] = result.model
    response.headers["X-Modela-Request-Id"] = request_id
    return result
