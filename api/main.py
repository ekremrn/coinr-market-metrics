"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import scanner, setups
from api.store import redis_store
from src.config import ApiConfig
from src.logging import get_logger

logger = get_logger("market-metrics-api")

_api_cfg = ApiConfig()

_docs_url = None if _api_cfg.production else "/docs"
_redoc_url = None if _api_cfg.production else "/redoc"
_openapi_url = None if _api_cfg.production else "/openapi.json"

app = FastAPI(
    title="Coinr Market Metrics",
    version="v1.3",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
    description="""
Real-time USDT-perpetual futures market metrics and AI-generated trade setups streamed via SSE.

### Data sources
- **Scanner job** — runs on a fixed schedule, analyses the full USDT-perpetual universe and writes a market snapshot to Redis.
- **Analysis agent** — evaluates individual symbols with an LLM and emits trade setups to Redis when conditions are met.

### Endpoints
- **Scanner** — REST snapshot + SSE streams for market state and top candidates.
- **Scanner History** — REST access to compact successful market snapshots from the last 48 hours.
- **Setups** — REST list + SSE stream for active AI-generated trade setups (last 120 min).
- **Setups History** — REST access to expired trade setups from the last 48 hours.

### Data freshness
Market snapshots are produced every `SCAN_INTERVAL_MINUTES` (default 15 min).  
Trade setups expire after 120 minutes.
""",
    openapi_tags=[
        {
            "name": "Scanner",
            "description": (
                "Market-wide metrics produced by the scanner job. "
                "Includes aggregate market state (regime, BTC direction, correlation, volatility) "
                "and the top-K candidate symbols ranked by attractiveness score."
            ),
        },
        {
            "name": "Setups",
            "description": (
                "AI-generated trade setups produced by the analysis agent. "
                "Each setup contains entry, stop-loss, and take-profit levels for a specific symbol. "
                "Active setups are those generated within the last 120 minutes."
            ),
        },
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_api_cfg.cors_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(scanner.router)
app.include_router(setups.router)


@app.on_event("shutdown")
async def shutdown() -> None:
    await redis_store.close()
