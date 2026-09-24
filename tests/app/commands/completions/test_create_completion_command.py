from types import SimpleNamespace

from pydantic_ai.messages import ModelRequest, ModelResponse

from app.commands.completions.create_completion_command import (
    CreateCompletionCommand,
    _merge_system_prompts,
    _split_messages,
)
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


def _msg(role, content):
    return SimpleNamespace(role=role, content=content)


def test_split_messages_collects_system_messages_instead_of_dropping_them():
    system_prompts, history, user_prompt = _split_messages(
        [
            _msg("system", "You are Dogy."),
            _msg("user", "hello?"),
            _msg("assistant", "Hi!"),
            _msg("system", "Current app context: account_id=abc"),
            _msg("user", "create a list"),
        ]
    )

    assert system_prompts == [
        "You are Dogy.",
        "Current app context: account_id=abc",
    ]
    assert [type(m) for m in history] == [ModelRequest, ModelResponse]
    assert user_prompt == "create a list"


def test_split_messages_without_system_messages():
    system_prompts, history, user_prompt = _split_messages([_msg("user", "hi")])

    assert system_prompts == []
    assert history == []
    assert user_prompt == "hi"


def test_merge_system_prompts_puts_config_prompt_first():
    assert (
        _merge_system_prompts("config", ["caller one", "caller two"])
        == "config\n\ncaller one\n\ncaller two"
    )


def test_merge_system_prompts_caller_only():
    assert _merge_system_prompts(None, ["caller"]) == "caller"


def test_merge_system_prompts_returns_none_when_empty():
    assert _merge_system_prompts(None, []) is None
