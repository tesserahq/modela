import pytest

from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.services.tools.registry import validate_enabled_tools


def test_valid_subset_accepted():
    validate_enabled_tools(["search_knowledge_base"])


def test_none_and_empty_are_no_ops():
    validate_enabled_tools(None)
    validate_enabled_tools([])


def test_unknown_tool_name_rejected():
    with pytest.raises(InvalidParameterError):
        validate_enabled_tools(["search_knowledge_base", "delete_everything"])
