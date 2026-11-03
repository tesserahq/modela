"""What an LLM run loads stays usable after its short session closes."""

from uuid import uuid4

from app.commands.load_model_config import load_model_config
from app.repositories.mcp_server_repository import MCPServerRepository
from app.repositories.mcp_tool_catalog_repository import MCPToolCatalogRepository
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.mcp_server import MCPServerCreate


def _make_config(db):
    return ModelConfigRepository(db).create(
        {
            "slug": f"load-{uuid4().hex[:8]}",
            "name": "Load Test",
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.2,
        }
    )


def test_config_is_readable_after_the_session_closes(db, short_sessions):
    slug = _make_config(db).slug

    config, system_prompt = load_model_config(
        short_sessions, lambda repo: repo.get_by_slug(slug)
    )

    # The session committed and closed: an expired config would raise
    # DetachedInstanceError here.
    assert (config.slug, config.provider, config.model) == (slug, "openai", "gpt-4o")
    assert config.temperature == 0.2
    assert system_prompt is None


def test_mcp_servers_are_readable_after_the_session_closes(db, short_sessions):
    config = _make_config(db)
    server = MCPServerRepository(db).create_mcp_server(
        MCPServerCreate(
            server_id=f"load-{uuid4().hex[:8]}",
            name="Load MCP",
            url="https://example.com/mcp",
            enabled=True,
        )
    )
    config.mcp_servers.append(server)
    db.commit()

    connections = MCPToolCatalogRepository(
        short_sessions
    )._model_config_server_connections(config.id, None)

    [(loaded, headers)] = connections
    assert (loaded.server_id, loaded.url) == (
        server.server_id,
        "https://example.com/mcp",
    )
    assert loaded.tool_prefix is None or isinstance(loaded.tool_prefix, str)
    assert headers == {}
