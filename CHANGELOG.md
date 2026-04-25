# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.1] - 2026-04-25 — Reviewer Feedback Patch

### Fixed (P0 — bugs blocking real use)

- **#2.1 Foreign-key ordering** (`engine/runner.py`): `create_run` now happens
  before the first `RUN_STARTED` event. Previously every run silently lost its
  first event due to SQLite foreign-key rejection (events table → runs table)
  because `_emit` used a bare `try/except` that swallowed the integrity error.
- **#2.2 Per-node timeout** (`engine/runner.py`): each node is now wrapped in
  `asyncio.wait_for(node_fn(state), timeout=remaining)`. Previously a hanging
  LLM call would block the whole run forever — `task_timeout_seconds` was only
  checked between nodes, never inside.
- **#2.3 CancelledError handling** (`engine/runner.py`): `asyncio.CancelledError`
  is now caught explicitly and produces a `RUN_CANCELLED` event +
  `status=cancelled`. Previously `cancel_search` left the store stuck on
  `running`.
- **Subdomain matching** (`retrieval/policy_filter.py`): `reddit.com` in
  `blocked_domains` now correctly blocks `www.reddit.com` and `old.reddit.com`.
  Previously it didn't match any subdomain, silently breaking every source
  policy. `*.spam.*` glob patterns continue to work.
- **#3 Result persistence** (`store/schema.py`, `store/store.py`,
  `engine/runner.py`): `runs` table gains `result_json` and `error` columns;
  `EventStore.finish_run(state)` persists report / evidence / critic /
  token_usage on every run finalisation. Previously `poll_search` returned a
  placeholder `"(see store for full report; v0.2 will inline)"` — v0.1 was
  effectively unusable.
- **#1 Unified task lifecycle** (`engine/manager.py`, `adapters/http/app.py`,
  `adapters/mcp/server.py`): new `RunManager` owned by the `DeepSearch` facade
  is the single source of truth for `start / poll / cancel / steer / result /
  events`. HTTP and MCP adapters no longer maintain their own
  `_running_tasks` dicts, so a task started via HTTP is now visible to MCP and
  vice versa.
- **#5 Resource lifecycle** (`facade.py`, `agents/base.py`): provider clients
  (Tavily / Serper / Crossref / Firecrawl / Jina / Cohere) are now allocated
  once in a `DeepSearch._provider_pool` and reused across all queries. Each
  call to `_build_context` no longer leaks an httpx connection pool.
  `DeepSearch.aclose()` now closes everything; `AgentContext.aclose()` is
  available for cases that own their clients.

### Added (P1 — performance + quality)

- **#4 Quick Search Fast Lane** (`engine/fast_lane.py`): `quick_search` now
  bypasses the 6-node graph entirely. The new path is
  `search → policy_filter → optional reranker (top-K) → fetch top-2 full
  text → reporter-lite (single LLM call)`, with explicit per-stage budgets
  derived from `timeout_seconds`. Default timeout dropped from 30 s to 12 s.
- **New HTTP routes**: `GET /v1/runs/{id}/poll` (long-poll, max 25 s) and
  `GET /v1/runs/{id}/result` (immediate persisted result).
- **MCP tools** now return real reports through `RunManager.poll`.

### Tests

- `test_runner_run_started_event_persisted` — guards against the foreign-key
  regression returning.
- `test_runner_node_timeout_marks_run_timeout` — verifies per-node timeout.
- `test_manager_start_poll_returns_real_report` — `poll` returns the actual
  markdown body, not a placeholder.
- `test_manager_cancel_sets_cancelled_status` — store records `cancelled`
  status after cancel.
- `test_filter_blocks_subdomain` — `reddit.com` in blocked_domains blocks
  `www.reddit.com` / `old.reddit.com` but not `notreddit.com`.
- `test_filter_blocks_wildcard` — glob patterns still work.
- Existing steer tests now seed `runs` rows so they're compatible with the
  enforced foreign key.

Total: **48 unit tests passing** (was 36 in v0.1.0).

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
