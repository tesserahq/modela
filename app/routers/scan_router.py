import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.rbac import build_rbac_dependencies, infer_project
from app.commands.scan.create_scan_command import CreateScanCommand
from app.db import get_db
from app.schemas.scan import ScanFileRequest, ScanResponse
from tessera_sdk.server.dependencies.auth import get_current_user

router = APIRouter(tags=["scan"])
RBAC_RESOURCE = "completion"
_rbac = build_rbac_dependencies(resource=RBAC_RESOURCE, project_resolver=infer_project)


@router.post(
    "/scan/file",
    response_model=ScanResponse,
    dependencies=[Depends(_rbac["create"])],
)
async def scan_file(
    payload: ScanFileRequest,
    project_id: str = Depends(infer_project),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    request_id = str(uuid.uuid4())
    return await CreateScanCommand(db).execute_file(
        file_url=payload.file_url,
        mime_type=payload.mime_type,
        model_slug=payload.model,
        project_id=project_id,
        request_id=request_id,
        user_id=current_user.id,
    )
