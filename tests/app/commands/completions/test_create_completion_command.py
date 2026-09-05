from app.commands.completions.create_completion_command import CreateCompletionCommand
from app.repositories.model_config_repository import ModelConfigRepository
from app.schemas.mcp_tool import MCPCatalogTool


def _make_config(db, **overrides):
    data = {
        "slug": "cfg",
        "name": "Cfg",
        "provider": "openai",
        "model": "gpt-4o",
    }
    data.update(overrides)
    return ModelConfigRepository(db).create(data)


def _fake_mcp_tool():
    return MCPCatalogTool(
        qualified_name="server.tool",
        original_name="tool",
        description="a tool",
        input_schema={"type": "object", "properties": {}},
        server_id="server-id",
    )


def test_no_mcp_tools_and_no_enabled_tools_returns_none(db):
    config = _make_config(db)
    command = CreateCompletionCommand(db)
    assert command._build_toolsets(config, [], user_id=None) is None


def test_enabled_tools_only_builds_single_builtin_toolset(db):
    config = _make_config(db, enabled_tools=["search_knowledge_base"])
    command = CreateCompletionCommand(db)

    toolsets = command._build_toolsets(config, [], user_id=None)

    assert toolsets is not None
    assert len(toolsets) == 1
    assert toolsets[0].id == "builtin"


def test_mcp_tools_and_enabled_tools_combine_into_two_toolsets(db):
    config = _make_config(db, enabled_tools=["search_knowledge_base"])
    command = CreateCompletionCommand(db)

    toolsets = command._build_toolsets(config, [_fake_mcp_tool()], user_id=None)

    assert toolsets is not None
    assert len(toolsets) == 2
    assert {t.id for t in toolsets} == {"mcp", "builtin"}


def test_mcp_tools_only_matches_pre_existing_behavior(db):
    config = _make_config(db)
    command = CreateCompletionCommand(db)

    toolsets = command._build_toolsets(config, [_fake_mcp_tool()], user_id=None)

    assert toolsets is not None
    assert len(toolsets) == 1
    assert toolsets[0].id == "mcp"
