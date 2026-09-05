"""Built-in tool registry API: read-only listing for admin UI consumption."""

from fastapi import APIRouter, Depends, Request
from tessera_sdk.server.dependencies.auth import (
    get_current_user,  # type: ignore[import-untyped]
)

from app.auth.rbac import build_rbac_dependencies
from app.schemas.tool_registry import ToolInfo
from app.services.tools.registry import BUILTIN_TOOL_REGISTRY

router = APIRouter(
    prefix="/tools",
    tags=["tools"],
)


async def infer_domain(request: Request) -> str | None:
    # The built-in tool registry is product-wide, not project-scoped — same
    # "global domain" pattern used by mcp_servers/knowledge_documents.
    return "*"


RESOURCE_TOOLS = "tool"
rbac = build_rbac_dependencies(
    resource=RESOURCE_TOOLS,
    domain_resolver=infer_domain,
)


@router.get("", response_model=list[ToolInfo])
def list_tools(
    _authorized: bool = Depends(rbac["read"]),
    _current_user=Depends(get_current_user),
) -> list[ToolInfo]:
    """List modela-provided built-in tools available for ModelConfig.enabled_tools."""
    return [
        ToolInfo(name=name, description=description)
        for name, description in BUILTIN_TOOL_REGISTRY.items()
    ]
