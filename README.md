# coinr-market-metrics

A standalone microservice that computes market-state metrics from Binance USDT perpetual futures and publishes live snapshots to Redis, with historical snapshots stored in MongoDB. A FastAPI server exposes SSE endpoints for streaming updates.

## What it does
- Every 15 minutes (right after a 15m candle closes), it fetches top USDT perpetual symbols by 24h quote volume (excluding blacklist) and always includes BTCUSDT for calculations.
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

## Metrics overview (v1.1)
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
- `extension_score`: EMA/range/ATR-based stretch score
- `fakeout_risk`: quick-failure risk for the current move
- `execution_cost_score`: spread + volatility usability score
- `long_score`, `short_score`: side-specific setup quality
- `regime_label`, `diagnostic_tags`: richer symbol context without changing compatibility flags

## Notes
- Storage:
  - Redis keys: `market_state:latest`, `market_state:symbols:latest`, `market_state:candidates:latest`
  - Pubsub: `market_state:events`
  - Shared `MONGO_URI` is used for both Mongo connections
  - Market snapshots are stored in hardcoded DB `coinr-market-metrics`, collection `market_state_snapshots`
  - Historical setups are read from hardcoded DB `coinr`, collection `analyses`

## Cronjob example (every 15 minutes)
If you want the task to run via cron and exit after completion, add a crontab entry like:

```cron
*/15 * * * * cd /../coinr-market-metrics && docker compose run market-scanner -d
```

Notes:
- Make sure `docker compose -f docker-compose.infra.yml up -d` is running for Redis/MongoDB.
- Adjust the path to your local project directory.
