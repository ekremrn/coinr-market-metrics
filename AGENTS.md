# AGENTS.md

## Purpose

This repository is a Python microservice that computes Binance USDT perpetual futures market metrics, writes the latest market state to Redis, stores compact history in MongoDB, and exposes REST/SSE endpoints through FastAPI. This file is an operating guide for humans and AI agents so future changes follow the architecture already present in the repo instead of introducing arbitrary parallel patterns.

## Repository snapshot

- **Main technologies:** Python, FastAPI, Pydantic v2, Redis, MongoDB, asyncio, NumPy, Docker Compose.
- **Runtime(s):** Python 3.12 in Alpine-based Docker images. The API runs under `uvicorn`; the scanner runs as a one-shot Python process.
- **Framework(s):** FastAPI for HTTP/SSE, Pydantic models for API response contracts. There is no ORM, no migration tool, no frontend framework, and no in-repo scheduler.
- **Key dependencies:** `fastapi`, `uvicorn[standard]`, `pydantic`, `redis`, `pymongo`, `numpy`, `requests`, `binance-futures-python` from GitHub, `pytest`.
- **Build/test/lint commands:**
  - `make setup` creates `.env` from `.env.example`.
  - `make infra-up` starts Redis and MongoDB from `docker-compose.infra.yml`.
  - `make services-up` starts the API and scanner service definitions from `docker-compose.yml`.
  - `make up` starts infrastructure, waits briefly, then starts services.
  - `docker compose -f docker-compose.yml run --rm market-scanner` triggers one immediate scanner run.
  - `python3 -m pytest -q` runs the current test suite when dependencies are installed.
  - No lint, formatter, type-check, tox, or CI command is configured in this repo.
- **Deployment target:** Docker Compose is the only detectable deployment target. Both service compose files expect an external Docker network named `coinr-network`. No cloud, Kubernetes, or CI/CD manifests are present.

## Current project structure

- `api/` - FastAPI read/stream service. It owns HTTP routing, response models, and the shared async Redis store used by route handlers.
- `api/main.py` - application bootstrap: FastAPI metadata, CORS setup, router registration, and Redis shutdown cleanup.
- `api/models.py` - Pydantic response contracts for market snapshots, symbol metrics, historical snapshots, and trade setups. API schema compatibility belongs here.
- `api/store.py` - module-level `AsyncRedisStore` singleton for the API process.
- `api/routes/scanner.py` - REST and SSE routes for latest market snapshots, candidate streams, and compact market history. Reads Redis for latest state and MongoDB for history.
- `api/routes/setups.py` - REST and SSE routes for externally produced CoinR trade setups. Reads active setup signals from Redis and expired accepted setups from MongoDB.
- `scanner-job/` - one-shot market scanner worker package and Docker image. It fetches Binance data, computes metrics, and persists/publishes snapshots.
- `scanner-job/main.py` - scanner orchestration entrypoint. It selects the universe, fetches 5m/15m/1h klines plus book/funding data, computes features and metrics, stabilizes market bias from recent history, writes Redis keys, publishes Redis events, and inserts MongoDB history.
- `src/` - shared code used by both the API and scanner. Domain logic and infrastructure wrappers belong here when they are not route-only or job-only.
- `src/config.py` - environment-backed dataclass config and shared database name constants. New env vars should be defined here and mirrored in `.env.example`.
- `src/binance_client.py` - Binance Futures REST wrapper with async rate limiting, retry/backoff behavior, and universe selection quality gates.
- `src/storage.py` - Redis, async Redis, Redis pubsub fan-out, and MongoDB wrappers. API and scanner code should use these wrappers instead of raw clients.
- `src/snapshot_archive.py` - pure additive Mongo archive shape and declarative index specs for full-universe replay.
- `src/mongo_maintenance.py` - dry-run-first snapshot index application; writes require an explicit confirmation token.
- `src/indicators.py` - lightweight NumPy indicator implementations such as EMA, SMA, ATR, ADX, and RSI.
- `src/utils.py` - small cross-cutting helpers for clamping, UTC timestamps, and safe float parsing.
- `src/logging.py` - stdout logger factory with env-controlled level and structured context support.
- `src/metrics/` - market metric domain package. This is the core business logic boundary.
- `src/metrics/__init__.py` - public import surface for metric callers: feature building, market metrics, symbol metrics, candidate selection, and bias stabilization.
- `src/metrics/klines.py` - Binance kline array parsing and current-bar elapsed fraction logic.
- `src/metrics/features.py` - raw symbol feature extraction from klines, order book, and funding data. It owns 5m entry fields, 15m/1h support-resistance derivation, and nearest valid level distance calculations.
- `src/metrics/normalizers.py` - pure numeric normalization, weighting, return, correlation, liquidity, volume, and direction helpers.
- `src/metrics/scores.py` - per-symbol and market weighting score functions that operate on feature dictionaries. It owns side-specific entry-risk scoring, including strict CoinR hard-reject mirrors.
- `src/metrics/symbol.py` - symbol-level metric assembly, regime label selection, diagnostic tags, v1.3 side-aware extension and entry-risk fields, and compatibility flags.
- `src/metrics/market.py` - market-level aggregation, regime selection, environment scoring, breakout/fakeout aggregation, and historical bias smoothing/hysteresis.
- `src/metrics/candidates.py` - candidate ranking and candidate payload projection, including additive v1.3 fields consumed by CoinR.
- `tests/` - pytest suite covering metric behavior and API route contracts. Tests use local fixtures and monkeypatch storage/database boundaries.
- `README.md` - user-facing overview, local run instructions, endpoint list, metric descriptions, Redis/Mongo key notes, and cron example.
- `requirements.txt` - single Python dependency manifest used by both Docker images.
- `Makefile` - local Docker Compose convenience targets. It does not define tests, linting, or formatting.
- `docker-compose.yml` - API and one-shot scanner service definitions using `.env` and the external `coinr-network`.
- `docker-compose.infra.yml` - Redis 7 and MongoDB 7 local infrastructure with volumes and health checks.
- `.env.example` - documented scanner, storage, logging, and API env vars.

## Architecture overview

The repo is a small two-process, dataflow-oriented Python service:

1. The scanner process is the only writer for market metrics. It loads `AppConfig`, selects a Binance USDT perpetual universe, always adds `BTCUSDT` for reference calculations, fetches order book, funding, and kline data, computes metrics, writes Redis latest keys, publishes a Redis event, and inserts a MongoDB history document.
2. The API process is a read/stream adapter. It does not call Binance and does not compute market metrics. It reads latest snapshots/candidates from Redis, streams updates by subscribing to Redis pubsub notifications, and reads compact history from MongoDB with a short Redis cache.
3. `src/metrics` owns the business rules. Raw market data becomes feature dictionaries in `features.py`; numeric primitives live in `normalizers.py`; score formulas live in `scores.py`; symbol and market assemblers create API-facing metric dictionaries.
4. Pydantic models are used at the HTTP boundary, not throughout the internal metric pipeline. The scanner mostly passes plain dictionaries between metric functions and storage.
5. Redis is the live state and fan-out mechanism. MongoDB is the historical store. The API history endpoints query MongoDB and cache the compact result in Redis for 300 seconds.
6. The trade setup routes are an integration point with another system, described in code as the CoinR analysis agent. This repo consumes setup Redis keys/events and MongoDB analysis records; it does not generate those setups.

Request/data flow for market state:

1. `scanner-job/main.py::run_once`
2. `BinanceDataFetcher.select_universe`
3. `fetch_book_tickers`, `fetch_funding_rates`, and `fetch_klines_for_symbols` for 5m, 15m, and 1h candles
4. `build_symbol_features`
5. `build_market_metrics`
6. `load_recent_market_history` and `stabilize_market_bias`
7. `build_symbol_metrics`
8. `select_candidates`
9. Redis keys: `market_state:latest`, `market_state:symbols:latest`, `market_state:candidates:latest`
10. Redis pubsub channel: `market_state:events`
11. MongoDB collection: `coinr-market-metrics.market_state_snapshots`

`INCLUDE_SYMBOLS_IN_MONGO=true` archives the full `symbols` universe plus
explicit `replay_archive` completeness metadata. The default compact archive
remains backward compatible and retains `candidates`.
12. API routes in `api/routes/scanner.py` expose latest, history, and SSE streams.

Key boundaries:

- Binance access belongs in `src/binance_client.py` and scanner orchestration. Do not fetch Binance data from API routes.
- Metric formulas belong under `src/metrics`. Do not bury score math inside the scanner or API routes.
- Storage mechanics belong in `src/storage.py`; route modules may compose store calls but should not create bespoke Redis/Mongo clients.
- API contracts belong in `api/models.py`; every externally visible payload field should be represented there.
- Scanner-only sequencing can stay in `scanner-job/main.py` until it becomes reusable or large enough to justify moving into `src`.

## Architectural decisions

- **Decision:** The scanner and API are separate processes with separate responsibilities.
  - **Evidence:** `api/Dockerfile` runs `uvicorn api.main:app`; `scanner-job/Dockerfile` runs `python scanner-job/main.py`; `docker-compose.yml` defines `app` and `market-scanner` separately.
  - **Implication:** New metric production work belongs in the scanner path. New read/stream behavior belongs in the API path. Do not make API requests trigger Binance scans unless adding an explicit, reviewed operational endpoint.

- **Decision:** API routes are read-side adapters over Redis and MongoDB.
  - **Evidence:** `api/routes/scanner.py` reads `market_state:*` Redis keys and Mongo history; `api/routes/setups.py` reads CoinR setup keys and Mongo `analyses`; neither route module imports `src.metrics` or `BinanceDataFetcher`.
  - **Implication:** Keep routes thin. They may validate, serialize, stream, cache, and call storage wrappers, but they should not contain market business logic.

- **Decision:** `src.metrics` is the public metric package surface.
  - **Evidence:** `src/metrics/__init__.py` exports `build_symbol_features`, `build_symbol_metrics`, `build_market_metrics`, `select_candidates`, and `stabilize_market_bias`; the scanner imports those names from `src.metrics`.
  - **Implication:** New metric capabilities that callers need should be exposed through `src.metrics`. Direct imports from deep metric modules should be reserved for tests or genuinely internal composition.

- **Decision:** Metric computation is a staged dictionary pipeline, not a class-heavy domain model.
  - **Evidence:** `build_symbol_features` returns feature dictionaries; `build_market_metrics`, `build_symbol_metrics`, and `select_candidates` accept and return dictionaries/lists; Pydantic models are only in `api/models.py`.
  - **Implication:** Preserve the staged pipeline unless doing a deliberate refactor. Add fields by extending feature/metric dictionaries and API models consistently.

- **Decision:** Numeric helpers and score formulas are centralized and normalized to stable ranges.
  - **Evidence:** `src/metrics/normalizers.py` contains `normalize_range`, `normalize_symmetric`, `weighted_mean`, `volume_score`, and `liquidity_score_from_spread`; `src/metrics/scores.py` clamps composite scores and risks to `[0, 1]`.
  - **Implication:** New score math should reuse these helpers. Do not introduce duplicate normalization curves inside route handlers or scanner orchestration.

- **Decision:** `BTCUSDT` is a mandatory reference symbol for calculations, even when it is not part of the selected universe.
  - **Evidence:** `fetch_all_market_data` and `build_snapshot` use `sorted({*universe_symbols, "BTCUSDT"})`; symbol metrics are emitted only for selected universe symbols.
  - **Implication:** Any market-level or relative-strength feature must account for the reference BTC feature and must not accidentally expose BTC as a candidate unless it is actually in the selected universe.

- **Decision:** Redis owns latest/live state and pubsub notifications; MongoDB owns history.
  - **Evidence:** `store_snapshot` writes `market_state:latest`, `market_state:symbols:latest`, `market_state:candidates:latest`, publishes `market_state:events`, and inserts `market_state_snapshots` into MongoDB.
  - **Implication:** Use Redis for current snapshots and SSE fan-out. Use MongoDB for historical queries. Do not turn MongoDB into the hot path for latest state.

- **Decision:** SSE fan-out uses one Redis pubsub listener per channel per API process, not one Redis pubsub connection per client.
  - **Evidence:** `BroadcastHub` in `src/storage.py` multiplexes Redis messages to subscriber queues and is used by `AsyncRedisStore.subscribe`.
  - **Implication:** New SSE routes should use `AsyncRedisStore.subscribe` and unsubscribe in `finally`. Do not create per-client raw Redis pubsub connections.

- **Decision:** History endpoints return compact, successful records and cache them briefly.
  - **Evidence:** `/market/history` queries `status: "ok"` and projects only `_id`, `ts`, `ts_ms`, and `market`; `/setups/history` projects only `position`; both cache results in Redis for 300 seconds.
  - **Implication:** New history endpoints should project only fields they return and should use explicit versioned cache keys with TTLs.

- **Decision:** External failures during scanning are non-fatal when possible.
  - **Evidence:** scanner helpers append standardized `record_error` dictionaries; `build_snapshot` sets `status` to `partial` when errors exist; Mongo insert failure mutates the snapshot to `partial`.
  - **Implication:** Prefer partial snapshots with clear `errors` over failing the whole scan for recoverable per-symbol/store failures.

- **Decision:** Trade setups are consumed from an external producer.
  - **Evidence:** `api/main.py` describes an "Analysis agent"; `api/routes/setups.py` reads `coinr:trade_signals:*`, `coinr:trade_signals:events`, and MongoDB database `coinr`, collection `analyses`.
  - **Implication:** Do not add setup-generation logic to this repo without changing its service boundary intentionally.

- **Decision:** Configuration is environment-backed dataclasses, not Pydantic settings.
  - **Evidence:** `src/config.py` defines frozen dataclasses using `os.getenv`; `.env.example` documents the vars.
  - **Implication:** Add new environment configuration in `src/config.py`, then update `.env.example`, README, Docker usage, and tests where relevant. Do not scatter `os.getenv` calls across the codebase.

## Default rules for future changes

- Prefer placing market-domain logic under `src/metrics/`. New feature extraction belongs in `features.py`; new pure normalization or return math belongs in `normalizers.py`; new score formulas belong in `scores.py`; final payload assembly belongs in `symbol.py` or `market.py`.
- Do not put score formulas, regime rules, Binance parsing, or candidate ranking inside FastAPI route modules.
- New scanner behavior should preserve the run-once worker model. Scheduling belongs outside the Python process unless the repo is deliberately converted to a long-running worker.
- New API endpoints should live in `api/routes/`, define or reuse Pydantic response models in `api/models.py`, and be registered from `api/main.py`.
- Blocking MongoDB calls from async routes must run through `asyncio.to_thread`, matching the existing history endpoints.
- Redis and MongoDB access should go through `RedisStore`, `AsyncRedisStore`, and `MongoStore`. Only extend these wrappers when storage behavior is shared or repeated.
- New env vars must be added to `src/config.py` and `.env.example` together. Keep README examples aligned with actual defaults.
- Metric payload field names should be stable `snake_case`. Use `*_score` for normalized `[0, 1]` quality values, `*_risk` for normalized `[0, 1]` risk values, `*_regime` or `*_label` for categorical state, and `*_tags` for explanatory lists.
- Preserve compatibility fields. If adding richer explanations, prefer `diagnostic_tags`-style additive fields over expanding strict `Literal` compatibility flags unless all clients are ready.
- When changing the market snapshot schema, update `api/models.py`, tests, README metric docs, cache-key versions, FastAPI app version, and `METRICS_VERSION` defaults in one change.
- CoinR compatibility fields must stay additive and side-aware. `long_extension_score` / `short_extension_score` complement the symmetric `extension_score`; `long_entry_risk` / `short_entry_risk` must return `1.0` when CoinR deterministic hard-reject equivalents are detected.
- Market scores should clamp outputs to explicit ranges and should handle `None`/missing inputs without crashing.
- Universe selection quality gates should stay in `BinanceDataFetcher.select_universe` or scanner config, not in downstream metric formulas.
- Keep `BTCUSDT` inclusion explicit in scanner calculations. Do not rely on universe ranking to include BTC.
- Candidate ranking should remain a projection over already built symbol metrics. Do not refetch or recompute symbol features inside `select_candidates`.
- New history reads should filter to successful/accepted records as appropriate, project compact payloads, and cache with a named TTL constant.
- Use UTC-aware timestamps for persisted and emitted records. Existing helpers are `utc_now_iso()` and `utc_now_ms()`.
- Add tests for threshold behavior, compatibility fields, and API parsing whenever changing metric formulas or response models.
- Tests should monkeypatch stores and route helper functions rather than requiring live Redis, MongoDB, or Binance.
- Only place code in `src/utils.py` when it is genuinely cross-cutting across modules. If a helper is only used by one metric stage, keep it private in that module.
- Avoid adding new top-level packages unless there is a clear new process or boundary. Shared code belongs under `src`; API adapters belong under `api`; scanner orchestration belongs under `scanner-job`.
- Do not introduce an ORM or migration framework casually. This repo currently uses direct MongoDB collections and explicit projections.
- Do not add frontend/UI code to this repository. It exposes API and SSE contracts for consumers.

## Allowed patterns

- Plain functions with typed signatures for metric computation.
- Feature dictionaries as internal pipeline objects when extending existing metric stages.
- Pydantic `BaseModel` and `Literal` types for HTTP response schemas.
- Additive API fields with defaults or `Optional[...]` when preserving backward compatibility.
- Constants near route modules for cache keys, TTLs, event channels, and history windows.
- `asyncio.gather` and `asyncio.as_completed` for scanner fetch concurrency, behind `BinanceDataFetcher` rate limiting.
- `asyncio.to_thread` for blocking MongoDB work from async request handlers.
- Redis pubsub notification followed by re-reading latest state from Redis for SSE streams.
- Focused pytest tests using fixture builders and `monkeypatch` for external boundaries.
- Short comments explaining non-obvious metric thresholds, hysteresis, and compatibility decisions.

## Discouraged or legacy patterns

- **Compatibility naming:** Some older tests still contain `v11` in filenames or fixture values. Treat those as compatibility coverage unless the endpoint contract itself is being renamed.
- **Current default:** `TOP_N=30` and `CANDIDATES_K=20` are aligned between `.env.example` and `AppConfig`.
- **Inconsistent:** `docker-compose.infra.yml` initializes `coinr_market_metrics`, while code uses MongoDB database `coinr-market-metrics`. Treat `src/config.py` as the source of truth unless correcting the compose file.
- **Legacy compatibility:** `/setups/history` includes Mongo records without `decision_stage` for backward compatibility. New producer records should include explicit accepted decision stages.
- **Transitional:** `api/main.py` uses FastAPI `@app.on_event("shutdown")`. For larger lifecycle work, prefer moving to FastAPI lifespan handling instead of adding more event hooks.
- **Exception-only:** Direct deep imports from `src.metrics.market` are present in tests. Production callers should prefer the `src.metrics` public surface.
- **Documentation drift:** `api/main.py` still describes `SCAN_INTERVAL_MINUTES`, but there is no scanner loop or config var by that name in code. Do not rely on that variable unless implementing it deliberately.
- **Misleading setup text:** `make setup` tells users to edit Binance API keys, but the current Binance client is instantiated with `api_key=None` and `api_secret=None`. Do not add secret requirements unless authenticated Binance endpoints are introduced.
- **Avoid:** Per-client Redis pubsub connections, route-level Binance fetches, unversioned Redis history cache keys, hidden env vars, and new metric fields that are not reflected in Pydantic models/tests.

## Feature addition playbook

1. Decide the boundary first: metric production, API read/stream behavior, external setup consumption, storage/config, or documentation.
2. For scanner/metric changes, add any required env config in `src/config.py` and `.env.example`.
3. If new Binance data is needed, extend `src/binance_client.py` and fetch it from `scanner-job/main.py`; keep rate limiting and partial-error behavior.
4. Add raw per-symbol values in `src/metrics/features.py` when the data is derived from klines, book tickers, funding, or price action.
5. Add reusable numeric transforms to `src/metrics/normalizers.py`; add composite score/risk formulas to `src/metrics/scores.py`.
6. Expose final market-level fields from `src/metrics/market.py` or symbol-level fields from `src/metrics/symbol.py`.
7. If candidates need the field, add it to the projection in `src/metrics/candidates.py`.
8. Update `api/models.py` for every externally visible field, including constraints and literals where appropriate.
9. Update scanner snapshot persistence if the field belongs in Mongo history. Keep Mongo history compact unless there is a strong reason to store full symbol lists.
10. Add or update tests in the current metrics test module, such as `tests/test_metrics_v13.py`, for formula behavior and compatibility, and API tests when response models or route behavior changes.
11. Update README metric lists, endpoint notes, Redis/Mongo key notes, and version strings when payload contracts change.
12. Run `python3 -m pytest -q` before handing off, or state clearly why it could not be run.

## Decision policy for ambiguous cases

- When choosing between `api/` and `src/`, put reusable logic in `src/` and HTTP-specific composition in `api/`.
- When choosing between `scanner-job/` and `src/`, keep one-off orchestration in `scanner-job/main.py`; move logic to `src/` only when it is reusable, independently testable, or part of the domain/infrastructure boundary.
- When choosing between metric modules, follow the pipeline order: parse/raw feature in `klines.py` or `features.py`, normalize in `normalizers.py`, score in `scores.py`, assemble payload in `symbol.py` or `market.py`, rank/project in `candidates.py`.
- When introducing a new abstraction, prefer a small function in the existing module. Add a class only for stateful external resources or lifecycle management, matching `BinanceDataFetcher`, `RedisStore`, `AsyncRedisStore`, `MongoStore`, and `BroadcastHub`.
- When a utility is only used by one feature or route, keep it private in that module. Promote it to shared only after repeated use appears.
- When a new API field could be either a strict enum/flag or an explanatory tag, prefer additive diagnostic tags unless clients need a stable enum contract.
- When data can come from Redis or MongoDB, use Redis for latest/active/live data and MongoDB for historical records.
- When there are multiple possible database names or key names, choose the constants and keys already used by code over README prose.
- When docs and code disagree, treat code and tests as current behavior, then update docs as part of the change.
- Do not create a new pattern when the existing wrappers, route layout, or metric pipeline is sufficient.

## Open questions / uncertainty

- `api/main.py` references `SCAN_INTERVAL_MINUTES`, but no such config is implemented. The scanner is currently a one-shot job intended for external cron/container scheduling.
- MongoDB database naming differs between compose initialization (`coinr_market_metrics`) and code (`coinr-market-metrics`). The code-level constant is what actually controls collection access.
- No MongoDB indexes are declared in this repo, even though history queries depend on `ts_ms` and setup history queries depend on `timestamp`.
- No CI, lint, format, or type-check configuration exists. Test-only quality enforcement is currently the strongest available signal.
- The CoinR analysis agent setup schema is inferred from `api/models.py`, `api/routes/setups.py`, README notes, and tests. Its producer implementation is outside this repository.
- The repo has no package metadata (`pyproject.toml`, `setup.cfg`, or similar). Imports rely on running from the repository root or setting `PYTHONPATH=/app` in Docker.

## Maintenance note

Update `AGENTS.md` whenever the service boundary, metric pipeline, API contract, storage keys, deployment model, or testing/tooling setup meaningfully changes. This file should stay aligned with actual code and tests, not aspirational architecture.
