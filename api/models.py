"""Response models for the Coinr Market Metrics API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Direction = Literal["bullish", "bearish", "neutral"]
MarketRegime = Literal["TRENDING", "SELECTIVE", "OFF"]
VolatilityRegime = Literal["LOW", "NORMAL", "HIGH"]
CorrelationRegime = Literal["COUPLED", "MIXED", "DECOUPLED"]
RecommendedMode = Literal["LONG_ONLY", "SHORT_ONLY", "SELECTIVE", "OFF"]
TakerDominance = Literal["buy_dominant", "sell_dominant", "neutral"]
SymbolFlag = Literal["adx15_low", "high_spread", "volume_weak", "taker_conflict"]


class MarketState(BaseModel):
    """Market-wide aggregate metrics derived from the full universe."""

    tradeability_score: float = Field(..., ge=0, le=1, description="Overall market tradeability [0–1]. Higher = more trending conditions across the universe.")
    chop_score: float = Field(..., ge=0, le=1, description="Fraction of choppy (low-ADX) symbols, normalised [0–1]. Higher = more chop.")
    market_regime: MarketRegime = Field(..., description="Qualitative market regime: TRENDING, SELECTIVE, or OFF.")
    recommended_mode: RecommendedMode = Field(..., description="Suggested trading mode based on BTC direction and alt bias.")

    btc_direction_1h: Direction = Field(..., description="BTC 1-hour EMA-crossover direction.")
    btc_trend_strength: float = Field(..., ge=0, le=1, description="BTC 1h ADX normalised to [0–1].")
    alt_directional_bias_15m: float = Field(..., ge=0, le=1, description="Fraction of alts trending bullish on 15m [0=all bearish, 0.5=mixed, 1=all bullish].")
    btc_alt_corr_mean_1h: float = Field(..., ge=0, le=1, description="Mean BTC-alt 1h Pearson correlation normalised to [0–1].")
    btc_alt_corr_raw: float = Field(..., ge=-1, le=1, description="Mean BTC-alt 1h Pearson correlation (raw, -1 to 1).")
    correlation_regime: CorrelationRegime = Field(..., description="Correlation regime: COUPLED (>0.6), MIXED, or DECOUPLED (<0.3).")

    volatility_level_15m: float = Field(..., ge=0, le=1, description="ATR% mean across universe, normalised [0–1].")
    volatility_regime: VolatilityRegime = Field(..., description="Volatility regime derived from mean ATR%.")
    atrp_mean_15m: float = Field(..., description="Raw mean ATR% (15m) across the universe.")

    volume_health_15m: float = Field(..., ge=0, le=1, description="Mean volume score across universe [0–1]. >0.5 = above-average volume.")

    funding_rate_avg_8h: float = Field(..., ge=0, le=1, description="Mean 8h funding rate normalised to [0–1]. 0.5 = neutral.")
    funding_rate_direction: Literal["positive", "negative", "neutral"] = Field(..., description="Funding rate bias direction.")

    adx15_mean: float = Field(..., description="Raw mean ADX (14) across all 15m series.")
    chop_ratio: float = Field(..., ge=0, le=1, description="Ratio of symbols with ADX < 22.")


class SymbolMetrics(BaseModel):
    """Per-symbol technical metrics and composite scores."""

    symbol: str = Field(..., description="Trading pair symbol, e.g. BTCUSDT.")
    dir_1h: Direction = Field(..., description="1-hour EMA-crossover direction.")
    dir_15m: Direction = Field(..., description="15-minute EMA-crossover direction.")
    adx_15m: Optional[float] = Field(None, description="ADX (14) on 15m. Values >25 indicate trend.")
    spread_bps: Optional[float] = Field(None, description="Best bid/ask spread in basis points.")
    atrp_15m: Optional[float] = Field(None, description="ATR (14) as % of price on 15m.")
    vol_ratio_15m: Optional[float] = Field(None, description="Current 15m volume vs 20-bar SMA. >1 = above average.")
    taker_dominance_15m: TakerDominance = Field(..., description="Taker buy/sell dominance over the last 4 bars.")
    liquidity_score: float = Field(..., ge=0, le=1, description="Spread-derived liquidity score [0–1]. Higher = tighter spread.")
    trend_score: float = Field(..., ge=0, le=1, description="ADX-derived trend score [0–1].")
    attractiveness_score: float = Field(..., ge=0, le=1, description="Composite candidate attractiveness score [0–1].")
    flags: List[SymbolFlag] = Field(default_factory=list, description="Warning flags: adx15_low, high_spread, volume_weak, taker_conflict.")


class UniverseInfo(BaseModel):
    top_n: int = Field(..., description="Number of symbols selected by volume rank.")
    candidates_k: int = Field(..., description="Number of top candidates returned.")
    blacklist: List[str] = Field(..., description="Symbols excluded from the universe.")
    symbols: List[str] = Field(..., description="Universe symbols after blacklist filtering.")
    calc_symbols: List[str] = Field(..., description="Universe + BTCUSDT used for market metric calculation.")
    volume_ranked: List[Dict[str, Any]] = Field(..., description="Volume-ranked list with quote_volume.")
    total_symbols: int = Field(..., description="Total universe size.")


class MarketSnapshot(BaseModel):
    """Full market state snapshot produced by one scanner run."""

    ts: str = Field(..., description="ISO-8601 UTC timestamp of the snapshot.")
    ts_ms: int = Field(..., description="Unix timestamp in milliseconds.")
    version: str = Field(..., description="Metrics schema version.")
    status: Literal["ok", "partial"] = Field(..., description="'ok' = no errors; 'partial' = some symbols or stores failed.")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Non-fatal errors encountered during the scan.")
    universe: UniverseInfo
    market: MarketState
    symbols: List[SymbolMetrics] = Field(..., description="Per-symbol metrics for all universe symbols.")
    candidates: List[SymbolMetrics] = Field(..., description="Top-K symbols by attractiveness_score.")


class SnapshotResponse(BaseModel):
    market_state: Optional[MarketSnapshot] = Field(None, description="Full market snapshot. Null if no scan has run yet.")
    candidates: Optional[List[SymbolMetrics]] = Field(None, description="Top-K candidate symbols. Null if no scan has run yet.")


class HistoricalMarketSnapshot(BaseModel):
    """Compact historical market snapshot returned by the history endpoint."""

    ts: str = Field(..., description="ISO-8601 UTC timestamp of the snapshot.")
    ts_ms: int = Field(..., description="Unix timestamp in milliseconds.")
    market: MarketState


class TradeSetup(BaseModel):
    """Trade setup (position recommendation) produced by the analysis agent."""

    symbol: str = Field(..., description="Trading pair symbol, e.g. BTCUSDT.")
    position_type: Literal["long", "short"] = Field(..., description="Direction of the trade.")
    entry_price: float = Field(..., description="Recommended entry price.")
    stop_loss_price: float = Field(..., description="Stop-loss price.")
    take_profit_prices: List[float] = Field(default_factory=list, description="Ordered list of take-profit target prices.")
    valid_for_minutes: int = Field(60, description="How long this setup is considered active, in minutes.")
    notes: List[str] = Field(default_factory=list, description="Analyst notes generated by the LLM.")
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp when the setup was generated.")
