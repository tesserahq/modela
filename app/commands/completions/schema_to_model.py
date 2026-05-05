from __future__ import annotations

from typing import Any, Literal, Optional

import pydantic
from fastapi import HTTPException

_UNSUPPORTED_KEYWORDS = frozenset({"$ref", "oneOf", "allOf", "anyOf"})
_SCALAR_TYPES: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
}


def schema_to_model(
    schema: dict[str, Any], *, name: str = "StructuredOutput"
) -> type[pydantic.BaseModel]:
    """Convert a flat JSON Schema object dict to a dynamic Pydantic model.

    Raises HTTPException(422) for unsupported or invalid schemas.
    """
    if schema.get("type") != "object":
        raise HTTPException(
            status_code=422,
            detail="output_schema must have a top-level type of 'object'.",
        )
    _check_unsupported_keywords(schema)
    return _build_model(schema, name)


def _check_unsupported_keywords(schema: dict[str, Any]) -> None:
    found = _UNSUPPORTED_KEYWORDS & schema.keys()
    if found:
        kw = ", ".join(f"'{k}'" for k in sorted(found))
        raise HTTPException(
            status_code=422,
            detail=f"output_schema uses unsupported keyword(s): {kw}. Use a flat, fully-inlined schema.",
        )
    for prop_schema in schema.get("properties", {}).values():
        _check_unsupported_keywords(prop_schema)
    if "items" in schema:
        _check_unsupported_keywords(schema["items"])


def _build_model(schema: dict[str, Any], name: str) -> type[pydantic.BaseModel]:
    properties: dict[str, Any] = schema.get("properties", {})
    required: set[str] = set(schema.get("required", []))
    fields: dict[str, Any] = {}

    for field_name, prop_schema in properties.items():
        python_type = _resolve_type(prop_schema, parent=f"{name}_{field_name}")
        if field_name in required:
            fields[field_name] = (python_type, ...)
        else:
            fields[field_name] = (Optional[python_type], None)

    return pydantic.create_model(name, **fields)


def _resolve_type(prop: dict[str, Any], *, parent: str) -> Any:
    t = prop.get("type")

    if t in _SCALAR_TYPES:
        if t == "string" and "enum" in prop:
            return Literal[tuple(prop["enum"])]  # type: ignore[return-value]
        return _SCALAR_TYPES[t]

    if t == "array":
        items = prop.get("items", {})
        item_type = _resolve_type(items, parent=f"{parent}_item")
        return list[item_type]

    if t == "object":
        return _build_model(prop, name=parent)

    if t is None:
        raise HTTPException(
            status_code=422,
            detail="output_schema property is missing a 'type' field.",
        )
    raise HTTPException(
        status_code=422,
        detail=f"output_schema contains unsupported property type: '{t}'.",
    )
