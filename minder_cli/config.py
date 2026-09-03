"""Resolve the api-gateway URL + token: CLI flag → env → config file → default.

The config file (``~/.config/minder/config.json``, honouring ``XDG_CONFIG_HOME``)
caches the token from ``minder login`` and the api-url, so later commands need no
flags. Env vars ``MINDER_API_URL`` / ``MINDER_TOKEN`` override the file.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_API_URL = "http://localhost:8000"


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "minder" / "config.json"


def load_file() -> Dict[str, Any]:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_token(token: str, api_url: Optional[str] = None) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_file()
    data["token"] = token
    if api_url:
        data["api_url"] = api_url
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def resolve_api_url(flag: Optional[str] = None) -> str:
    return (
        flag
        or os.environ.get("MINDER_API_URL")
        or load_file().get("api_url")
        or DEFAULT_API_URL
    )


def resolve_token(flag: Optional[str] = None) -> Optional[str]:
    return flag or os.environ.get("MINDER_TOKEN") or load_file().get("token")
