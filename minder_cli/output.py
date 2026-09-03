"""Render an api-gateway response for the terminal.

Default is a compact, human-readable view (a bulleted list for collections, a
``key: value`` block for objects, plain text for a chat reply); ``--json`` prints
the raw JSON instead. Unknown shapes fall back to JSON so nothing is hidden.
"""

import json
from typing import Any, List

_ID_KEYS = ("name", "id", "title", "model")
_DESC_KEYS = ("description", "summary", "status")
# keys that are pagination metadata, not a second payload — their presence
# alongside a single list still counts as a "pure" collection wrapper.
_META_KEYS = frozenset({"count", "total", "limit", "offset", "page", "size"})


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
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        # A PURE collection wrapper — exactly one list plus only pagination
        # metadata (/v1/plugins {plugins,count,total,...}, /v1/status {services},
        # models/RAG {items,total}) — renders as rows + a shown/total count.
        if len(list_keys) == 1 and all(
            k == list_keys[0] or k in _META_KEYS for k in data
        ):
            rows = data[list_keys[0]]
            total = data.get("total")
            count = f"{len(rows)} shown" + (f" of {total}" if total is not None else "")
            return f"{_rows(rows) or '(none)'}\n({count})"
        # Anything else (a scalar payload mixed with a list — e.g. rag query's
        # {answer, sources}, or plugins config's {schema, values}) shows EVERY
        # field so nothing important is silently dropped.
        return _obj(data)
    return str(data)


def _obj(obj: dict) -> str:
    lines = []
    for key, value in obj.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            body = _rows(value)
            lines.append(
                "\n".join("  " + ln for ln in body.split("\n")) if body else "  (none)"
            )
        elif isinstance(value, dict):
            lines.append(f"{key}: {json.dumps(value, default=str)}")
        else:
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
