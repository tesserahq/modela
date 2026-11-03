"""Builds a pydantic-ai FunctionToolset from a ModelConfig's `enabled_tools`
list, wrapping the built-in tool implementations (registry.py) as plain
functions that each open a short session. pydantic-ai runs sync tool functions
in a thread, so the search stays off the event loop."""

from pydantic_ai.toolsets.function import FunctionToolset

from app.db import SessionFactory
from app.services.knowledge.search import search_knowledge_base_chunks


def build_builtin_toolset(
    sessions: SessionFactory, enabled_tools: list[str] | None
) -> FunctionToolset | None:
    """Returns None if `enabled_tools` is empty/None or names nothing this
    implementation recognizes yet (the registry and this builder are two
    separate pieces of code, kept from drifting apart by save-time validation
    in app.services.tools.registry, but this stays defensive regardless)."""
    if not enabled_tools:
        return None

    tools = []

    if "search_knowledge_base" in enabled_tools:

        def search_knowledge_base(query: str) -> list[str]:
            """Semantically search the product knowledge base and return the
            most relevant excerpts for the given query. Use this to ground
            answers about product concepts, features, or documentation
            instead of guessing."""
            with sessions() as db:
                return search_knowledge_base_chunks(db, query)

        tools.append(search_knowledge_base)

    if not tools:
        return None

    return FunctionToolset(tools, id="builtin")
