"""Render an api-gateway response for the terminal.

Default is a compact, human-readable view (a bulleted list for collections, a
``key: value`` block for objects, plain text for a chat reply); ``--json`` prints
the raw JSON instead. Unknown shapes fall back to JSON so nothing is hidden.
"""

import json
from typing import Any, List

_ID_KEYS = ("name", "id", "title", "model")
_DESC_KEYS = ("description", "summary", "status")


def render(data: Any, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(data, indent=2, default=str)
    return _human(data).rstrip("\n") or "(empty)"


def _human(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return _rows(data) or "(none)"
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            body = _rows(items) or "(none)"
            total = data.get("total")
            count = f"{len(items)} shown" + (
                f" of {total}" if total is not None else ""
            )
            return f"{body}\n({count})"
        return _kv(data)
    return str(data)


def _kv(obj: dict) -> str:
    lines = []
    for key, value in obj.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _rows(items: List[Any]) -> str:
    lines = []
    for item in items:
        if isinstance(item, dict):
            name = next((str(item[k]) for k in _ID_KEYS if item.get(k)), None)
            desc = next((str(item[k]) for k in _DESC_KEYS if item.get(k)), None)
            if name and desc:
                lines.append(f"- {name}  —  {desc}")
            elif name:
                lines.append(f"- {name}")
            else:
                lines.append("- " + json.dumps(item, default=str))
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)
