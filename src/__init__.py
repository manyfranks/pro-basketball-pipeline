"""
NBA SGP Engine - Path B Implementation

Market-first player prop analysis for NBA games.
Uses signal framework to detect edges where data disagrees with market lines.

Core components:
- signals/: Signal framework (line value, trend, usage, matchup, env, correlation)
- edge_calculator: Aggregates signals to calculate edge
- data_provider: NBA stats via nba_api
- odds_client: Player props from Odds API
"""

from .signals import (
    PropContext,
    SignalResult,
    ALL_SIGNALS,
)
from .edge_calculator import EdgeCalculator, EdgeResult, get_edge_calculator
from .data_provider import NBADataProvider, get_data_provider
from .odds_client import NBAOddsClient, PropLine, GameLine, get_odds_client

__all__ = [
    # Core classes
    'EdgeCalculator',
    'EdgeResult',
    'PropContext',
    'SignalResult',
    'NBADataProvider',
    'NBAOddsClient',
    'PropLine',
    'GameLine',
    # Singletons
    'get_edge_calculator',
    'get_data_provider',
    'get_odds_client',
    # Signal list
    'ALL_SIGNALS',
]

__version__ = '0.1.0'
