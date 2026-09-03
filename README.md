# cli

`minder` — a small command-line client over a **Minder** instance's api-gateway
(auth, health, plugins today; RAG / models / AI tools next). Open-source
companion to the platform, alongside `plugin-sdk`. Scope + roadmap: **#1**.

## Install

```bash
pip install "git+https://github.com/minderhq/cli"
```

## Use

```bash
minder --api-url http://localhost:8000 login    # prompts, caches a JWT
minder health                                    # api-gateway /health
minder status                                    # every service's health
minder plugins                                   # list registered plugins
```

Config resolves as **flag → env (`MINDER_API_URL` / `MINDER_TOKEN`) → `~/.config/minder/config.json` → default** (`http://localhost:8000`). `minder login` caches the token + url there so later commands need no flags.

Output is pretty JSON (scriptable); a richer human view is a follow-up.

## Develop

```bash
pip install -e ".[dev]"
black --check . && flake8 --max-line-length=100 --extend-ignore=E203,W503 . && mypy minder_cli && pytest -q
```

Apache-2.0.
