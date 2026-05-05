import pytest
from fastapi import HTTPException

from app.commands.completions.schema_to_model import schema_to_model


# --- valid schemas ---

def test_scalar_fields_map_to_correct_types():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "score": {"type": "number"},
            "count": {"type": "integer"},
            "active": {"type": "boolean"},
        },
        "required": ["name", "score", "count", "active"],
    }
    Model = schema_to_model(schema)
    instance = Model(name="x", score=1.5, count=3, active=True)
    assert instance.name == "x"
    assert instance.score == 1.5
    assert instance.count == 3
    assert instance.active is True


def test_required_fields_are_non_optional():
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }
    Model = schema_to_model(schema)
    with pytest.raises(Exception):
        Model()


def test_non_required_fields_default_to_none():
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": [],
    }
    Model = schema_to_model(schema)
    instance = Model()
    assert instance.value is None


def test_string_enum_becomes_literal():
    schema = {
        "type": "object",
        "properties": {
            "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
        },
        "required": ["sentiment"],
    }
    Model = schema_to_model(schema)
    instance = Model(sentiment="positive")
    assert instance.sentiment == "positive"

    with pytest.raises(Exception):
        Model(sentiment="unknown")


def test_array_of_scalars():
    schema = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        "required": ["tags"],
    }
    Model = schema_to_model(schema)
    instance = Model(tags=["a", "b"])
    assert instance.tags == ["a", "b"]


def test_nested_object():
    schema = {
        "type": "object",
        "properties": {
            "meta": {
                "type": "object",
                "properties": {"version": {"type": "integer"}},
                "required": ["version"],
            }
        },
        "required": ["meta"],
    }
    Model = schema_to_model(schema)
    instance = Model(meta={"version": 2})
    assert instance.meta.version == 2


def test_model_dump_returns_dict():
    schema = {
        "type": "object",
        "properties": {"label": {"type": "string"}},
        "required": ["label"],
    }
    Model = schema_to_model(schema)
    result = Model(label="hello").model_dump()
    assert result == {"label": "hello"}


# --- invalid schemas: 422 ---

def test_non_object_top_level_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        schema_to_model({"type": "string"})
    assert exc_info.value.status_code == 422


def test_ref_raises_422():
    schema = {
        "type": "object",
        "properties": {"value": {"$ref": "#/definitions/Foo"}},
    }
    with pytest.raises(HTTPException) as exc_info:
        schema_to_model(schema)
    assert exc_info.value.status_code == 422
    assert "$ref" in exc_info.value.detail


def test_one_of_raises_422():
    schema = {"type": "object", "oneOf": [{"type": "string"}]}
    with pytest.raises(HTTPException) as exc_info:
        schema_to_model(schema)
    assert exc_info.value.status_code == 422


def test_all_of_raises_422():
    schema = {"type": "object", "allOf": [{"type": "string"}]}
    with pytest.raises(HTTPException) as exc_info:
        schema_to_model(schema)
    assert exc_info.value.status_code == 422


def test_any_of_raises_422():
    schema = {"type": "object", "anyOf": [{"type": "string"}]}
    with pytest.raises(HTTPException) as exc_info:
        schema_to_model(schema)
    assert exc_info.value.status_code == 422


def test_unsupported_keyword_in_nested_property_raises_422():
    schema = {
        "type": "object",
        "properties": {
            "value": {"type": "string", "$ref": "#/definitions/Foo"},
        },
    }
    with pytest.raises(HTTPException) as exc_info:
        schema_to_model(schema)
    assert exc_info.value.status_code == 422


def test_unsupported_property_type_raises_422():
    schema = {
        "type": "object",
        "properties": {"value": {"type": "null"}},
        "required": ["value"],
    }
    with pytest.raises(HTTPException) as exc_info:
        schema_to_model(schema)
    assert exc_info.value.status_code == 422
