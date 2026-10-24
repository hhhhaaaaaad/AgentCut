"""Strict JSON decoding for bounded, explicitly injected model adapters."""

import json

from app.schemas.script_contracts_v1 import require


def model_json_object(text: str):
    require(isinstance(text, str), "model response must be text")
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    elif text.startswith("```\n") and text.endswith("```"):
        text = text[4:-3].strip()

    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value

    def invalid_constant(_):
        raise ValueError("nonfinite JSON number")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
    require(isinstance(value, dict), "model output must be an object")
    return value
