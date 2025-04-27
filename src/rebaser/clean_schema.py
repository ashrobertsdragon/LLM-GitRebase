from google.genai.types import SchemaDict
from typing import overload


def _resolve_ref(reference: str, definitions: dict) -> dict:
    """Resolve a $ref reference within a JSON schema."""
    ref_path = reference.replace("#/$defs/", "").split("/")
    current = definitions
    for part in ref_path:
        if part not in current:
            return {"$ref": reference}
        current = current[part]
    return current


def _inline_ref(reference: str, definitions: dict) -> dict:
    return _inline(_resolve_ref(reference, definitions))


def _inline_anyof(items: list, definitions: dict) -> dict:
    """Converts anyOf list to dictionary with nullable property."""
    has_null_type = any(
        isinstance(item, dict) and item.get("type") == "null" for item in items
    )
    non_null_items = [
        _inline(item, definitions)
        for item in items
        if not (isinstance(item, dict) and item.get("type") == "null")
    ]
    if has_null_type and len(non_null_items) == 1:
        result = dict(non_null_items[0])
        result["nullable"] = True
        return result
    return {"anyOf": non_null_items}


@overload
def _inline(obj: dict, definitions: dict | None = None) -> dict: ...
@overload
def _inline(obj: list, definitions: dict | None = None) -> list: ...
@overload
def _inline(obj: str, definitions: dict | None = None) -> str: ...
def _inline(
    obj: dict | list | str, definitions: dict | None = None
) -> dict | list | str:
    """Recursively cleans a JSON schema."""
    _definitions = definitions or {}
    if isinstance(obj, dict):
        inlined_object = {}
        for key, value in obj.items():
            if key in ["additionalProperties", "$schema", "default"]:
                continue
            if (
                key == "$ref"
                and isinstance(value, str)
                and value.startswith("#/$defs/")
            ):
                inlined_object |= _inline_ref(value, _definitions)
            elif key == "anyOf" and isinstance(value, list):
                inlined_object.update(_inline_anyof(value, _definitions))
            else:
                inlined_object[key] = _inline(value)
        return inlined_object
    elif isinstance(obj, list):
        return [_inline(item, _definitions) for item in obj]
    return obj


def clean_schema(schema: dict) -> SchemaDict:
    """Inlines Pydantic $ref definitions within a JSON schema."""
    definitions: dict = schema.get("$defs", {})
    updated_schema = _inline(schema, definitions)

    updated_schema["properties"].pop("self")
    updated_schema["required"].remove("self")
    for field in ["$defs", "title"]:
        updated_schema.pop(field, None)

    return SchemaDict(**updated_schema)
