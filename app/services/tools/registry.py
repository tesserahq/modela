"""Hardcoded registry of modela-provided ("built-in") tools that a ModelConfig
can opt into via `enabled_tools`. Separate from MCP-server tools, which are
discovered dynamically per attached server."""

from app.exceptions.invalid_parameter_error import InvalidParameterError

BUILTIN_TOOL_REGISTRY: dict[str, str] = {
    "search_knowledge_base": (
        "Semantically search the product knowledge base and return relevant excerpts."
    ),
}


def validate_enabled_tools(names: list[str] | None) -> None:
    """Reject any name in `enabled_tools` that isn't a registered built-in tool."""
    if not names:
        return
    unknown = [name for name in names if name not in BUILTIN_TOOL_REGISTRY]
    if unknown:
        raise InvalidParameterError(
            f"Unknown built-in tool(s): {sorted(unknown)}; must be a subset of "
            f"{sorted(BUILTIN_TOOL_REGISTRY)}"
        )
