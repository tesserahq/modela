import json
import time
import uuid
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
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

    if payload.stream:
        config_slug, delta_gen = await CreateCompletionCommand(db).stream_execute(
            payload, project_id, request_id, user_id=current_user.id
        )
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created_ts = int(time.time())

        async def _sse():
            first = True
            async for delta in delta_gen:
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": config_slug,
                    "choices": [
                        {
                            "index": 0,
                            "delta": (
                                {"role": "assistant", "content": delta}
                                if first
                                else {"content": delta}
                            ),
                            "finish_reason": None,
                        }
                    ],
                }
                first = False
                yield f"data: {json.dumps(chunk)}\n\n"
            final = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": config_slug,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _sse(),
            media_type="text/event-stream",
            headers={
                "X-Modela-Config-Slug": config_slug,
                "X-Modela-Request-Id": request_id,
            },
        )

    result = await CreateCompletionCommand(db).execute(
        payload, project_id, request_id, user_id=current_user.id
    )
    response.headers["X-Modela-Config-Slug"] = result.model
    response.headers["X-Modela-Request-Id"] = request_id
    return result
