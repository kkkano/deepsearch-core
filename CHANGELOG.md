# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-04-25

### Added — Initial Release

- **Core Engine**
  - 200-line GraphRunner (no LangGraph dependency)
  - 5-node pipeline: check_clarity → supervisor → planner → fan_out_research → critic → reporter
  - Multi-agent fan-out with `asyncio.Semaphore` concurrency control
  - Immutable State with Pydantic models

- **Steer Mechanism** (inspired by OpenDeepResearch)
  - Three scopes: `current_step` / `global` / `next_step`
  - SQLite `steer_commands` table
  - Runner checkpoints both before and after each node

- **Event Sourcing**
  - SQLite `runs` / `events` / `steer_commands` / `query_cache` tables
  - WAL mode for concurrent access
  - Full replay via `EventStore.replay(run_id)`

- **LLM Layer**
  - httpx-based OpenAI-compatible client (no SDK lock-in)
  - Per-node model configuration (supervisor / planner / researcher / critic / reporter)
  - Streaming support
  - Anthropic prompt caching support

- **Search & Retrieval**
  - 6 search engines: Tavily, Serper, DuckDuckGo, Crossref, Firecrawl, Jina Reader
  - Cohere Reranker (v3.5)
  - HyDE (Hypothetical Document Embedding)
  - Query Expansion
  - Multi-engine racing + merging
  - Deduplication

- **Source Policies**
  - 4 built-in: `general` / `finance` / `tech` / `academic`
  - YAML-based config with trusted/blocked domains, weight boost, prompt addons
  - Custom inline dict policies supported

- **Adapters**
  - **MCP server** (FastMCP, stdio transport)
    - Tools: `quick_search`, `start_deep_search`, `poll_search`, `steer`, `cancel_search`
  - **HTTP API** (FastAPI + SSE + WebSocket)
    - REST: `/v1/search/quick`, `/v1/search/deep`, `/v1/search/deep/async`
    - SSE: `/v1/runs/{id}/stream`
    - WebSocket: `/ws/runs/{id}`
  - **CLI** (Typer + Rich)
    - Commands: `quick`, `deep`, `steer`, `status`, `replay`, `healthcheck`, `list-policies`

- **Documentation**
  - 7 detailed docs: ARCHITECTURE, BLUEPRINT, MCP_PROTOCOL, STEER_DESIGN, SOURCE_POLICY, EVAL_HARNESS, DEPLOYMENT, CONTRIBUTING
  - 5 working examples
  - Dockerfile + docker-compose.yml

- **Testing**
  - 7 unit test files (state, steer, store, policy, runner, dedup, event_bus)
  - Integration smoke test
  - pytest fixtures for mocked LLM

- **Eval Harness**
  - 2 datasets (general, finance) with 10 cases
  - Runner with scoring (factual / sources / latency)
  - Rich console output

### Known Limitations

- MCP HTTP/SSE transports are stub (stdio only fully working)
- DuckDuckGo regex parser is fragile (BeautifulSoup planned for v0.2)
- LLM-as-judge eval is string-match only (planned LLM eval in v0.2)
- No prompt caching auto-detection (manual flag)
- Cloudflare Workers / Modal Labs templates not yet provided

See [BLUEPRINT.md](docs/BLUEPRINT.md) for the full roadmap.
