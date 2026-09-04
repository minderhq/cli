# cli

`minder` — a small command-line client over a **Minder** instance's api-gateway
(auth, health, plugins, RAG, models, AI chat, plus billing, organizations, and
knowledge-graph correlations). Open-source companion to the platform, alongside
`plugin-sdk`. Scope + roadmap: **#1**.

## Install

```bash
pip install "git+https://github.com/minderhq/cli"
```

## Use

```bash
minder login --api-url http://localhost:8000    # prompts, caches a JWT
minder health                                    # api-gateway /health
minder status                                    # every service's health
minder plugins list                              # list registered plugins
minder plugins config crypto                     # show a plugin's config
minder plugins config crypto --set K=V           # update config (JWT)

minder rag kbs                                   # list knowledge bases
minder rag create-kb "My Docs" "my documents"    # create one
minder rag query <pipeline_id> "what is X?"      # ask a pipeline (--top-k N)
minder models list                               # list Ollama models
minder models pull llama3.2:latest               # pull one (admin)

minder ai tools                                  # the LLM's callable tools
minder ai chat "summarise RAG" --tools           # one-shot chat (JWT)

minder billing subscription                      # the org's current plan
minder billing checkout pro                      # start a hosted checkout for a tier
minder billing portal                            # customer-portal URL
minder org list                                  # the orgs you belong to
minder org switch <organization_id>              # switch active org (re-mints + caches JWT)
minder graph correlations "Acme Corp" --limit 5  # an entity's correlated entities/signals
```

Global flags (`--api-url`, `--token`, `--json`) go **after** the subcommand (git/docker style), e.g. `minder health --json`.

Config resolves as **flag → env (`MINDER_API_URL` / `MINDER_TOKEN`) → `~/.config/minder/config.json` → default** (`http://localhost:8000`). `minder login` caches the token + url there so later commands need no flags.

Output is a compact **human view** by default (a bulleted list for collections, `key: value` for objects, plain text for a chat reply); pass **`--json`** for raw JSON to pipe into `jq`.

## Develop

```bash
pip install -e ".[dev]"
black --check . && flake8 --max-line-length=100 --extend-ignore=E203,W503 . && mypy minder_cli && pytest -q
```

Apache-2.0.
