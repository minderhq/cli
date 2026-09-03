"""Terminal rendering: human view by default, raw JSON with as_json."""

import json

from minder_cli import output


def test_json_mode_is_raw_pretty_json():
    assert output.render({"a": 1}, as_json=True) == json.dumps({"a": 1}, indent=2)


def test_string_renders_as_plain_text():
    assert output.render("the answer") == "the answer"


def test_paginated_lists_items_with_count():
    data = {"items": [{"name": "crypto"}, {"name": "news"}], "total": 9}
    out = output.render(data)
    assert "- crypto" in out and "- news" in out
    assert "(2 shown of 9)" in out


def test_list_of_dicts_uses_name_and_description():
    out = output.render([{"name": "x", "description": "does x"}])
    assert out == "- x  —  does x"


def test_dict_renders_key_values():
    out = output.render({"healthy": True, "version": "1.0"})
    assert "healthy: True" in out and "version: 1.0" in out


def test_empty_and_none():
    assert output.render({"items": [], "total": 0}).startswith("(none)")
    assert output.render(None) == "(empty)"


def test_unknown_scalar_falls_back():
    assert output.render(42) == "42"


def test_plugins_wrapper_key_renders_as_list():
    # /v1/plugins → {"plugins":[...], "total":N} (not "items")
    data = {"plugins": [{"name": "crypto"}, {"name": "news"}], "total": 9, "count": 2}
    out = output.render(data)
    assert "- crypto" in out and "- news" in out and "(2 shown of 9)" in out


def test_status_services_wrapper_renders_as_list():
    # /v1/status → {"services":[...]}
    data = {"services": [{"name": "gateway", "status": "healthy"}]}
    out = output.render(data)
    assert out.startswith("- gateway  —  healthy")
    assert "(1 shown)" in out
