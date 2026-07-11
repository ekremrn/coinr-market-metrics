# coinr-market-metrics

A standalone microservice that computes market-state metrics from Binance USDT perpetual futures and publishes live snapshots to Redis, with historical snapshots stored in MongoDB. A FastAPI server exposes SSE endpoints for streaming updates.

## What it does
- Every 5 minutes it fetches top USDT perpetual symbols by 24h quote volume, filtered by minimum volume and maximum spread thresholds (universe quality gates), and always includes BTCUSDT for calculations.
- Computes standardized market metrics (0..1 scores + categorical regimes).
- Computes coin-level metrics and ranks top candidates.
- Writes latest snapshots to Redis and history to MongoDB.
- Serves SSE streams for live consumers.

## Running locally
1) Copy `.env.example` to `.env` and set your Redis and MongoDB connection strings.
2) Start infrastructure (Redis + MongoDB):

```bash
docker compose -f docker-compose.infra.yml up -d
```

3) Start services (API + market scanner):

```bash
docker compose -f docker-compose.yml up --build -d
```

4) Trigger a run (if you want a fresh snapshot immediately):

```bash
docker compose -f docker-compose.yml run --rm market-scanner
```

API:
- `GET /market` – latest snapshot (REST)
- `GET /market/history` – compact successful market snapshots from the last 48 hours
- `GET /market/stream` – stream full market snapshot
- `GET /candidates/stream` – stream candidate updates
- `GET /setups` – active trade setups, last 120 min (REST)
- `GET /setups/history` – expired trade setups from the last 48 hours
- `GET /setups/stream` – stream trade setups

Convenience:
- `make setup`, `make infra-up`, `make services-up`, `make up`

## API curl examples

### Market snapshot (REST)
```bash
curl http://localhost:8000/market
```

### Market history — last 48 hours (REST)
```bash
curl http://localhost:8000/market/history
```
Response is cached in Redis for 5 minutes.

### Stream full market snapshot (SSE)
```bash
curl -N http://localhost:8000/market/stream
```

### Stream top-K candidates (SSE)
```bash
curl -N http://localhost:8000/candidates/stream
```

### Active trade setups — last 120 min (REST)
```bash
curl http://localhost:8000/setups
```

### Setup history — expired setups from the last 48 hours (REST)
```bash
curl http://localhost:8000/setups/history
```
Response is cached in Redis for 5 minutes.

### Stream trade setups in real-time (SSE)
```bash
curl -N http://localhost:8000/setups/stream
```

## Metrics overview (v1.3)
Market metrics (all normalized 0..1 or categorical):
- `tradeability_score`: composite of trend breadth, direction consensus, liquidity health, volatility usability, and taker alignment
- `chop_score`: composite of low-ADX share, direction dispersion, and taker conflict share
- `market_regime`: OFF / SELECTIVE / TRENDING
- `btc_direction_1h`: EMA9 vs EMA21
- `btc_trend_strength`: ADX(1h), 0 at <=20, 1 at >=35
- `alt_directional_bias_15m`: based on bull/bear ratios
- `btc_alt_corr_mean_1h`: mean BTC-alt 1h return corr (last 24 bars), mapped to [0,1]
- `correlation_regime`: COUPLED / DECOUPLED / MIXED
- `volatility_level_15m`: mean ATR%, 0 at <=0.3%, 1 at >=1.2%
- `volatility_regime`: LOW / NORMAL / HIGH
- `volume_health_15m`: mean volume score from 15m volume ratios
- `recommended_mode`: OFF / SHORT_ONLY / LONG_ONLY / SELECTIVE
- `funding_rate_avg_8h`: average of latest funding rates across universe, normalized from -0.003..0.003 to [0,1]
- `funding_rate_direction`: positive / negative / neutral
- `regime_detail`: TREND / TREND_PULLBACK / TREND_EXTENSION / CHOP / EXPANSION / EXHAUSTION / MIXED
- `long_environment_score`, `short_environment_score`: aggregate side-specific tape quality
- `breakout_failure_risk`: market-level probability that continuation breaks down quickly
- `market_diagnostic_tags`: free-form diagnostics for the current tape

Coin metrics (per symbol in top N):
- `dir_1h`, `dir_15m`: EMA9 vs EMA21
- `adx_15m`, `atrp_15m`, `vol_ratio_15m`
- `spread_bps`, `taker_dominance_15m`
- `liquidity_score`, `trend_score`, `attractiveness_score`
- `flags`: lightweight explanations
- `relative_strength_score`: normalized BTC-relative strength
- `rsi_15m`: RSI(14) on the 15m timeframe
- `extension_score`: backward-compatible symmetric EMA/range/ATR/RSI-based stretch score
- `long_extension_score`, `short_extension_score`: side-aware stretch scores used by CoinR scanner routing
- `fakeout_risk`: quick-failure risk for the current move
- `execution_cost_score`: spread + volatility usability score
- `long_score`, `short_score`: side-specific setup quality
- `long_entry_risk`, `short_entry_risk`: side-specific entry-location risk; CoinR hard-reject equivalents return `1.0`
- `range_position_15m`, `range_position_5m_12`: current price position in recent 15m / 5m ranges
- `support_distance_pct_15m`, `resistance_distance_pct_15m`: nearest valid support/resistance distance from current price
- `support_touches_15m`, `resistance_touches_15m`: recent near-level touch counts
- `rsi_5m`, `taker_dominance_5m`: 5m entry quality fields aligned with CoinR analysis checks
- `regime_label`, `diagnostic_tags`: richer symbol context without changing compatibility flags
  - tags include `rsi_overbought` (RSI≥70) and `rsi_oversold` (RSI≤30)

## Notes
- Storage:
  - Redis keys: `market_state:latest`, `market_state:symbols:latest`, `market_state:candidates:latest`
  - Pubsub: `market_state:events`
  - Shared `MONGO_URI` is used for both Mongo connections
  - Market snapshots are stored in hardcoded DB `coinr-market-metrics`, collection `market_state_snapshots`
  - `INCLUDE_SYMBOLS_IN_MONGO=true` adds the full symbol universe plus
    `replay_archive` coverage metadata for CoinR historical scanner replay. The
    default remains the backward-compatible compact candidate archive.
  - `python -m src.mongo_maintenance` prints the snapshot index plan without a
    database connection. Applying it requires `--apply-indexes --confirm APPLY_INDEXES`.
  - `python -m src.snapshot_retention --days 7` previews expired compact
    snapshots. Deletion is bounded to 500 documents per batch by default and
    requires `--apply --confirm APPLY_RETENTION`.
  - Historical setups are read from hardcoded DB `coinr`, collection `analyses`

## Cronjob example (every 5 minutes)
The scanner is a one-shot job designed to be triggered by a cron. Add a crontab entry like:

```cron
*/5 * * * * cd /path/to/coinr-market-metrics && docker compose up market-scanner
15 1 * * * cd /path/to/coinr-market-metrics && docker compose run --rm --no-deps market-scanner python -m src.snapshot_retention --days 7 --apply --confirm APPLY_RETENTION
```

Notes:
- Make sure `docker compose -f docker-compose.infra.yml up -d` is running for Redis/MongoDB.
- Adjust the path to your local project directory.
- Uses `docker compose up` (not `run`) so Docker reuses the fixed `container_name` — if the previous scan is still running when the next cron fires, Docker will not start a second container, preventing parallel writes to Redis/MongoDB.
- Universe quality gates (`MIN_QUOTE_VOLUME`, `MAX_SPREAD_BPS`) filter out wash-traded / illiquid tokens before metric computation.
