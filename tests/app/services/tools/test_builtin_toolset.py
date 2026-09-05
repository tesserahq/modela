from unittest.mock import MagicMock, patch

from app.services.tools.builtin_toolset import build_builtin_toolset


def test_returns_none_for_no_enabled_tools():
    assert build_builtin_toolset(MagicMock(), None) is None
    assert build_builtin_toolset(MagicMock(), []) is None


def test_returns_none_for_unrecognized_tool_name():
    assert build_builtin_toolset(MagicMock(), ["not_implemented_tool"]) is None


def test_returns_toolset_with_builtin_id_when_search_enabled():
    toolset = build_builtin_toolset(MagicMock(), ["search_knowledge_base"])
    assert toolset is not None
    assert toolset.id == "builtin"


def test_tool_closure_delegates_to_search_module():
    db = MagicMock()
    toolset = build_builtin_toolset(db, ["search_knowledge_base"])
    tool_fn = toolset.tools["search_knowledge_base"].function

    with patch(
        "app.services.tools.builtin_toolset.search_knowledge_base_chunks",
        return_value=["excerpt"],
    ) as mock_search:
        result = tool_fn("what is X?")

    mock_search.assert_called_once_with(db, "what is X?")
    assert result == ["excerpt"]
