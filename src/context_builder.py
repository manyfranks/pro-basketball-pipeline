"""
NBA SGP Context Builder

Builds fully enriched PropContext objects by combining:
- Odds API data (line, odds)
- nba_api data (player stats, team stats, schedule)
- Injury data (availability)

This is the key integration point between data sources and the signal framework.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo

from .signals.base import PropContext, STAT_TYPE_TO_FIELD

logger = logging.getLogger(__name__)

ET = ZoneInfo('America/New_York')


class ContextBuilder:
    """
    Builds PropContext objects with full data enrichment.

    Data sources:
    - NBADataProvider: Player stats, team stats, schedule
    - NBAOddsClient: Lines, odds, game context
    - NBAInjuryChecker: Player availability

    Caches player contexts for efficiency (same player across multiple props).
    """

    def __init__(self):
        """Initialize context builder with lazy-loaded dependencies."""
        self._data_provider = None
        self._injury_checker = None

        # Cache player contexts (player_name -> PlayerContext)
        self._player_cache: Dict[str, Any] = {}

        # Cache team stats
        self._team_def_ratings: Dict[int, float] = {}
        self._team_paces: Dict[int, float] = {}
        self._team_rebounding: Dict[int, Dict[str, float]] = {}

        # Cache player tracking data
        self._player_reb_tracking: Dict[int, Dict] = {}
        self._player_pass_tracking: Dict[int, Dict] = {}

    @property
    def data_provider(self):
        """Lazy load data provider."""
        if self._data_provider is None:
            from .data_provider import get_data_provider
            self._data_provider = get_data_provider()
        return self._data_provider

    @property
    def injury_checker(self):
        """Lazy load injury checker."""
        if self._injury_checker is None:
            from .injury_checker import get_injury_checker
            self._injury_checker = get_injury_checker()
        return self._injury_checker

    def build_context(
        self,
        player_name: str,
        stat_type: str,
        line: float,
        over_odds: int,
        under_odds: int,
        game: Dict,
        game_date: str = None,
    ) -> Optional[PropContext]:
        """
        Build a fully enriched PropContext for a player prop.

        Args:
            player_name: Player's full name
            stat_type: Stat type ('points', 'rebounds', etc.)
            line: Betting line
            over_odds: American odds for over
            under_odds: American odds for under
            game: Game dict with home_team, away_team, total, spread
            game_date: Game date (YYYY-MM-DD)

        Returns:
            Fully enriched PropContext or None if player not found
        """
        # Get or fetch player context from cache
        player_ctx = self._get_player_context(player_name)
        if not player_ctx:
            logger.debug(f"Could not get context for {player_name}")
            return None

        # Determine home/away and opponent
        home_team = game.get('home_team', '')
        away_team = game.get('away_team', '')

        is_home = player_ctx.team == home_team or self._team_matches(player_ctx.team, home_team)
        opponent_team = away_team if is_home else home_team

        # Get opponent team ID
        opponent = self.data_provider.find_team(opponent_team)
        opponent_team_id = opponent['id'] if opponent else 0

        # Get opponent defensive stats
        opp_def_rating = self._get_team_def_rating(opponent_team_id)
        opp_pace = self._get_team_pace(opponent_team_id)

        # Get opponent rebounding stats (CRITICAL for rebounds props)
        opp_reb_stats = self._get_team_rebounding(opponent_team_id)

        # Get player tracking data for rebounds/assists
        reb_tracking = self._get_player_reb_tracking(player_ctx.player_id, player_ctx.team_id)
        pass_tracking = self._get_player_pass_tracking(player_ctx.player_id, player_ctx.team_id)

        # Get schedule context (B2B, 3-in-4)
        if game_date is None:
            game_date = datetime.now(ET).strftime('%Y-%m-%d')

        is_b2b = False
        is_3_in_4 = False
        if player_ctx.team_id:
            is_b2b = self.data_provider.is_back_to_back(player_ctx.team_id, game_date)
            is_3_in_4 = self.data_provider.is_three_in_four(player_ctx.team_id, game_date)

        # Get stat-specific averages
        season_avg = self._get_stat_average(player_ctx, stat_type, 'season')
        recent_avg = self._get_stat_average(player_ctx, stat_type, 'recent')

        # Build PropContext
        return PropContext(
            player_id=player_ctx.player_id,
            player_name=player_name,
            team=player_ctx.team,
            team_id=player_ctx.team_id,
            stat_type=stat_type,
            line=line,
            over_odds=over_odds,
            under_odds=under_odds,
            games_played=player_ctx.games_played,
            minutes_per_game=player_ctx.minutes_per_game,
            usage_pct=player_ctx.usage_pct,
            season_avg=season_avg,
            recent_avg=recent_avg,
            recent_minutes=player_ctx.min_l5,
            opponent_team=opponent_team,
            opponent_team_id=opponent_team_id,
            opponent_def_rating=opp_def_rating,
            opponent_pace=opp_pace,
            # Opponent rebounding (CRITICAL for rebounds)
            opponent_oreb_pct=opp_reb_stats.get('oreb_pct', 0.25),
            opponent_dreb_pct=opp_reb_stats.get('dreb_pct', 0.75),
            # Player rebound tracking
            reb_frequency=reb_tracking.get('reb_frequency', 0.0) if reb_tracking else 0.0,
            contested_reb_pct=reb_tracking.get('c_reb_pct', 0.0) if reb_tracking else 0.0,
            uncontested_reb_pct=reb_tracking.get('uc_reb_pct', 0.0) if reb_tracking else 0.0,
            # Player pass tracking
            passes_per_game=pass_tracking.get('passes_per_game', 0.0) if pass_tracking else 0.0,
            pass_to_ast_rate=pass_tracking.get('pass_to_ast_rate', 0.0) if pass_tracking else 0.0,
            potential_ast_per_game=pass_tracking.get('potential_ast_per_game', 0.0) if pass_tracking else 0.0,
            # Game context
            game_date=game_date,
            is_home=is_home,
            is_b2b=is_b2b,
            is_3_in_4=is_3_in_4,
            game_total=game.get('total'),
            spread=game.get('spread'),
            is_high_value=player_ctx.is_high_value,
        )

    def build_contexts_for_game(
        self,
        props: List[Any],  # List of PropLine
        game: Dict,
        game_date: str = None,
    ) -> List[PropContext]:
        """
        Build PropContext for all props in a game.

        More efficient than building one at a time due to caching.

        Args:
            props: List of PropLine objects
            game: Game dict
            game_date: Game date

        Returns:
            List of PropContext objects (may be shorter than input if some fail)
        """
        contexts = []

        for prop in props:
            ctx = self.build_context(
                player_name=prop.player_name,
                stat_type=prop.stat_type,
                line=prop.line,
                over_odds=prop.over_odds,
                under_odds=prop.under_odds,
                game=game,
                game_date=game_date,
            )
            if ctx:
                contexts.append(ctx)

        return contexts

    def _get_player_context(self, player_name: str):
        """Get player context from cache or fetch from data provider."""
        if player_name in self._player_cache:
            return self._player_cache[player_name]

        try:
            player_ctx = self.data_provider.get_player_context(player_name)
            self._player_cache[player_name] = player_ctx
            return player_ctx
        except Exception as e:
            logger.warning(f"Failed to get player context for {player_name}: {e}")
            self._player_cache[player_name] = None
            return None

    def _get_team_def_rating(self, team_id: int) -> float:
        """Get team defensive rating with caching."""
        if team_id in self._team_def_ratings:
            return self._team_def_ratings[team_id]

        try:
            rating = self.data_provider.get_team_def_rating(team_id)
            self._team_def_ratings[team_id] = rating
            return rating
        except Exception as e:
            logger.debug(f"Failed to get def rating for team {team_id}: {e}")
            return 112.0  # League average fallback

    def _get_team_pace(self, team_id: int) -> float:
        """Get team pace with caching."""
        if team_id in self._team_paces:
            return self._team_paces[team_id]

        try:
            pace = self.data_provider.get_team_pace(team_id)
            self._team_paces[team_id] = pace
            return pace
        except Exception as e:
            logger.debug(f"Failed to get pace for team {team_id}: {e}")
            return 99.0  # League average fallback

    def _get_team_rebounding(self, team_id: int) -> Dict[str, float]:
        """Get team rebounding rates with caching."""
        if team_id in self._team_rebounding:
            return self._team_rebounding[team_id]

        try:
            reb_stats = self.data_provider.get_team_rebounding_stats(team_id)
            self._team_rebounding[team_id] = reb_stats
            return reb_stats
        except Exception as e:
            logger.debug(f"Failed to get rebounding for team {team_id}: {e}")
            return {'oreb_pct': 0.25, 'dreb_pct': 0.75, 'reb_pct': 0.50}

    def _get_player_reb_tracking(self, player_id: int, team_id: int) -> Optional[Dict]:
        """Get player rebound tracking data with caching."""
        if player_id in self._player_reb_tracking:
            return self._player_reb_tracking[player_id]

        try:
            tracking = self.data_provider.get_player_rebound_tracking(player_id, team_id)
            self._player_reb_tracking[player_id] = tracking
            return tracking
        except Exception as e:
            logger.debug(f"Failed to get rebound tracking for player {player_id}: {e}")
            return None

    def _get_player_pass_tracking(self, player_id: int, team_id: int) -> Optional[Dict]:
        """Get player pass tracking data with caching."""
        if player_id in self._player_pass_tracking:
            return self._player_pass_tracking[player_id]

        try:
            tracking = self.data_provider.get_player_pass_tracking(player_id, team_id)
            self._player_pass_tracking[player_id] = tracking
            return tracking
        except Exception as e:
            logger.debug(f"Failed to get pass tracking for player {player_id}: {e}")
            return None

    def _get_stat_average(self, player_ctx, stat_type: str, period: str) -> float:
        """
        Get average for a specific stat type.

        Args:
            player_ctx: PlayerContext from data_provider
            stat_type: Stat type key
            period: 'season' or 'recent'

        Returns:
            Average value for the stat
        """
        # Map stat_type to field
        field_map = {
            'points': 'pts',
            'rebounds': 'reb',
            'assists': 'ast',
            'steals': 'stl',
            'blocks': 'blk',
            'threes': 'fg3m',
            'turnovers': 'tov',
            'fgm': 'fgm',
            'ftm': 'ftm',
        }

        # Combo stats
        combo_map = {
            'pra': ['pts', 'reb', 'ast'],
            'pr': ['pts', 'reb'],
            'pa': ['pts', 'ast'],
            'ra': ['reb', 'ast'],
            'blocks_steals': ['blk', 'stl'],
        }

        if stat_type in combo_map:
            # Sum the component stats
            if period == 'recent':
                return sum(
                    getattr(player_ctx, f'{f}_l5', 0) or 0
                    for f in combo_map[stat_type]
                )
            else:
                return sum(
                    getattr(player_ctx, f, 0) or 0
                    for f in combo_map[stat_type]
                )

        field = field_map.get(stat_type)
        if not field:
            return 0.0

        if period == 'recent':
            return getattr(player_ctx, f'{field}_l5', 0) or 0
        else:
            return getattr(player_ctx, field, 0) or 0

    def _team_matches(self, team1: str, team2: str) -> bool:
        """Check if two team identifiers match (handles full names vs abbreviations)."""
        if not team1 or not team2:
            return False

        # Direct match
        if team1.upper() == team2.upper():
            return True

        # Try looking up both
        t1 = self.data_provider.find_team(team1)
        t2 = self.data_provider.find_team(team2)

        if t1 and t2:
            return t1['id'] == t2['id']

        # Fuzzy match - check if one contains the other
        return team1.upper() in team2.upper() or team2.upper() in team1.upper()

    def clear_cache(self):
        """Clear all caches."""
        self._player_cache.clear()
        self._team_def_ratings.clear()
        self._team_paces.clear()
        self._team_rebounding.clear()
        self._player_reb_tracking.clear()
        self._player_pass_tracking.clear()


# Singleton instance
_context_builder: Optional[ContextBuilder] = None


def get_context_builder() -> ContextBuilder:
    """Get singleton context builder instance."""
    global _context_builder
    if _context_builder is None:
        _context_builder = ContextBuilder()
    return _context_builder
