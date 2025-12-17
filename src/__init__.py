"""
NBA SGP Engine - Path B Implementation

Market-first player prop analysis for NBA games.
Uses signal framework to detect edges where data disagrees with market lines.

Core components:
- signals/: Signal framework (line value, trend, usage, matchup, env, correlation)
- edge_calculator: Aggregates signals to calculate edge
- data_provider: NBA stats via nba_api
- odds_client: Player props from Odds API
- injury_checker: Player availability via ESPN API
- db_manager: Supabase database operations for parlays/legs/settlements
"""

from .signals import (
    PropContext,
    SignalResult,
    ALL_SIGNALS,
)
from .edge_calculator import EdgeCalculator, EdgeResult, get_edge_calculator
from .data_provider import NBADataProvider, get_data_provider
from .odds_client import NBAOddsClient, PropLine, GameLine, get_odds_client
from .injury_checker import (
    NBAInjuryChecker,
    PlayerAvailability,
    InjuryStatus,
    get_injury_checker,
)
from .db_manager import (
    NBASGPDBManager,
    get_db_manager,
)
from .thesis_generator import (
    ThesisGenerator,
    get_thesis_generator,
    generate_parlay_thesis,
)
from .settlement import (
    SettlementEngine,
    settle_parlays_for_date,
)
from .context_builder import (
    ContextBuilder,
    get_context_builder,
)

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
    # Injury checker
    'NBAInjuryChecker',
    'PlayerAvailability',
    'InjuryStatus',
    # Database manager
    'NBASGPDBManager',
    # Thesis generator
    'ThesisGenerator',
    'generate_parlay_thesis',
    # Settlement
    'SettlementEngine',
    'settle_parlays_for_date',
    # Context builder
    'ContextBuilder',
    # Singletons
    'get_edge_calculator',
    'get_data_provider',
    'get_odds_client',
    'get_injury_checker',
    'get_db_manager',
    'get_thesis_generator',
    'get_context_builder',
    # Signal list
    'ALL_SIGNALS',
]

__version__ = '0.5.0'
