"""coinr-market-metrics · metrics subpackage.

Public API — callers import directly from ``src.metrics``:

    from src.metrics import (
        build_symbol_features,
        build_symbol_metrics,
        build_market_metrics,
        select_candidates,
        stabilize_market_bias,
    )
"""

from .features import build_symbol_features
from .symbol import build_symbol_metrics
from .market import build_market_metrics, stabilize_market_bias
from .candidates import select_candidates

__all__ = [
    "build_symbol_features",
    "build_symbol_metrics",
    "build_market_metrics",
    "select_candidates",
    "stabilize_market_bias",
]
