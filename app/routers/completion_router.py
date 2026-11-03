import json
import time
import uuid

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from tessera_sdk.server.dependencies.auth import get_current_user

from app.auth.rbac import build_rbac_dependencies, infer_project
from app.commands.completions.create_completion_command import CreateCompletionCommand
from app.db import ShortSessions
from app.inference import StreamedExtension
from app.infra.logging_config import get_logger
from app.schemas.completion import CompletionCreate, CompletionResponse

router = APIRouter(tags=["completions"])
RBAC_RESOURCE = "completion"
_rbac = build_rbac_dependencies(resource=RBAC_RESOURCE, project_resolver=infer_project)

logger = get_logger()


@router.post(
    "/chat/completions",
    response_model=CompletionResponse,
    # `extensions` is set only for opted-in callers; everyone else gets the
    # unchanged response body.
    response_model_exclude_unset=True,
)
async def create_completion(
    payload: CompletionCreate,
    response: Response,
    # No request session: the command loads what it needs in short sessions
    # and holds no connection while the model runs or streams (SDD 0012).
    sessions: ShortSessions,
    project_id: str = Depends(infer_project),
    current_user=Depends(get_current_user),
):
    request_id = str(uuid.uuid4())

    if payload.stream:
        logger.info(
            f"Streaming completion for user {current_user.id} and project {project_id}"
        )
        command = CreateCompletionCommand(sessions)
        config_slug, delta_gen = await command.stream_execute(
            payload, project_id, request_id, user_id=current_user.id
        )
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created_ts = int(time.time())

        async def _sse():
            first = True
            async for delta in delta_gen:
                if isinstance(delta, StreamedExtension):
                    # Extensions ride in empty-choice chunks so text-only
                    # OpenAI-compatible clients skip them; adding a future
                    # channel does not require another transport branch.
                    extension_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": config_slug,
                        "choices": [],
                        "extensions": {delta.field: delta.payload},
                    }
                    yield f"data: {json.dumps(extension_chunk)}\n\n"
                    continue
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
                **_omitted_include_header(command),
            },
        )
    logger.info(
        f"Creating completion for user {current_user.id} and project {project_id}"
    )
    command = CreateCompletionCommand(sessions)
    result = await command.execute(
        payload, project_id, request_id, user_id=current_user.id
    )
    response.headers["X-Modela-Config-Slug"] = result.model
    response.headers["X-Modela-Request-Id"] = request_id
    response.headers.update(_omitted_include_header(command))
    return result


def _omitted_include_header(command: CreateCompletionCommand) -> dict[str, str]:
    """Name requested extension channels the ModelConfig does not expose.

    Sent as a header so streaming callers learn it before the body starts.
    """
    if not command.omitted_includes:
        return {}
    return {"X-Modela-Omitted-Include": ", ".join(command.omitted_includes)}
