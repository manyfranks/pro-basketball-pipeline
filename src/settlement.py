"""
NBA SGP Settlement Engine

Settles parlays against actual game box scores from nba_api.

Usage:
    from src.settlement import SettlementEngine, settle_parlays_for_date

    engine = SettlementEngine(db_manager)
    results = engine.settle_date(yesterday)
"""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo

from nba_api.stats.endpoints import scoreboardv2, boxscoretraditionalv3
from nba_api.stats.static import players

logger = logging.getLogger(__name__)

ET = ZoneInfo('America/New_York')


# Stat type mapping from our schema to nba_api column names
STAT_MAPPING = {
    'points': 'PTS',
    'rebounds': 'REB',
    'assists': 'AST',
    'steals': 'STL',
    'blocks': 'BLK',
    'threes': 'FG3M',
    'turnovers': 'TO',
    'fgm': 'FGM',
    'ftm': 'FTM',
    'minutes': 'MIN',
    # Combo stats - calculated
    'pra': ['PTS', 'REB', 'AST'],
    'pr': ['PTS', 'REB'],
    'pa': ['PTS', 'AST'],
    'ra': ['REB', 'AST'],
    'blocks_steals': ['BLK', 'STL'],
}


class SettlementEngine:
    """
    Settles NBA SGP parlays against actual box scores.

    Settlement Logic:
    1. Fetch box scores from nba_api
    2. For each parlay leg:
       - Find player's stats
       - Compare actual vs line
       - Mark WIN/LOSS/PUSH/VOID
    3. Parlay result:
       - All legs WIN → parlay WIN
       - Any leg LOSS → parlay LOSS
       - All legs VOID → parlay VOID
    """

    def __init__(self, db_manager=None):
        """
        Initialize settlement engine.

        Args:
            db_manager: NBASGPDBManager instance (lazy loaded if not provided)
        """
        self._db = db_manager

    @property
    def db(self):
        """Lazy load database manager."""
        if self._db is None:
            from src.db_manager import get_db_manager
            self._db = get_db_manager()
        return self._db

    def settle_date(self, settle_date: date) -> Dict[str, Any]:
        """
        Settle all parlays for a given date.

        Args:
            settle_date: Date to settle (typically yesterday)

        Returns:
            Settlement summary dict
        """
        result = {
            'date': str(settle_date),
            'parlays_found': 0,
            'parlays_settled': 0,
            'wins': 0,
            'losses': 0,
            'voids': 0,
            'errors': [],
        }

        # Get unsettled parlays for this date
        parlays = self.db.get_unsettled_parlays(game_date=settle_date)
        result['parlays_found'] = len(parlays)

        if not parlays:
            logger.info(f"No unsettled parlays for {settle_date}")
            return result

        logger.info(f"Settling {len(parlays)} parlays for {settle_date}")

        # Fetch box scores for the date
        box_scores = self._fetch_box_scores(settle_date)

        if not box_scores:
            logger.warning(f"No box scores available for {settle_date}")
            result['errors'].append("No box scores available")
            return result

        # Settle each parlay
        for parlay in parlays:
            try:
                settlement = self._settle_parlay(parlay, box_scores)

                if settlement:
                    result['parlays_settled'] += 1

                    if settlement['result'] == 'WIN':
                        result['wins'] += 1
                    elif settlement['result'] == 'LOSS':
                        result['losses'] += 1
                    else:
                        result['voids'] += 1

            except Exception as e:
                logger.error(f"Error settling parlay {parlay['id']}: {e}")
                result['errors'].append(f"Parlay {parlay['id'][:8]}: {e}")

        return result

    def _fetch_box_scores(self, game_date: date) -> Dict[str, Dict]:
        """
        Fetch box scores for all games on a date.

        Uses BoxScoreTraditionalV3 (required for 2025-26 season onwards).

        Returns:
            Dict mapping game_id to player stats dict
        """
        box_scores = {}

        try:
            # Get games from scoreboard
            date_str = game_date.strftime('%Y-%m-%d')
            scoreboard = scoreboardv2.ScoreboardV2(
                game_date=date_str,
                league_id='00'
            )

            games_df = scoreboard.game_header.get_data_frame()

            if games_df.empty:
                logger.info(f"No games found for {date_str}")
                return box_scores

            logger.info(f"Found {len(games_df)} games for {date_str}")

            # Fetch box score for each game using V3
            for _, game in games_df.iterrows():
                game_id = game['GAME_ID']

                try:
                    box = boxscoretraditionalv3.BoxScoreTraditionalV3(
                        game_id=game_id
                    )

                    data = box.get_dict()
                    box_data = data.get('boxScoreTraditional', {})

                    # Build player stats lookup from both teams
                    player_stats = {}

                    for team_key in ['homeTeam', 'awayTeam']:
                        team_data = box_data.get(team_key, {})
                        team_abbrev = team_data.get('teamTricode', '')
                        players_list = team_data.get('players', [])

                        for player in players_list:
                            first_name = player.get('firstName', '')
                            last_name = player.get('familyName', '')
                            player_name = f"{first_name} {last_name}".strip()
                            normalized = self._normalize_name(player_name)

                            stats_data = player.get('statistics', {})

                            stats = {
                                'player_id': player.get('personId'),
                                'player_name': player_name,
                                'team': team_abbrev,
                                'minutes': self._parse_minutes(stats_data.get('minutes', '0:00')),
                                'PTS': stats_data.get('points', 0) or 0,
                                'REB': stats_data.get('reboundsTotal', 0) or 0,
                                'AST': stats_data.get('assists', 0) or 0,
                                'STL': stats_data.get('steals', 0) or 0,
                                'BLK': stats_data.get('blocks', 0) or 0,
                                'FG3M': stats_data.get('threePointersMade', 0) or 0,
                                'TO': stats_data.get('turnovers', 0) or 0,
                                'FGM': stats_data.get('fieldGoalsMade', 0) or 0,
                                'FTM': stats_data.get('freeThrowsMade', 0) or 0,
                            }

                            player_stats[normalized] = stats

                    box_scores[game_id] = player_stats
                    logger.debug(f"Loaded box score for {game_id}: {len(player_stats)} players")

                except Exception as e:
                    logger.warning(f"Failed to fetch box score for {game_id}: {e}")

        except Exception as e:
            logger.error(f"Error fetching scoreboard: {e}")

        return box_scores

    def _settle_parlay(
        self,
        parlay: Dict,
        box_scores: Dict[str, Dict]
    ) -> Optional[Dict]:
        """
        Settle a single parlay.

        Args:
            parlay: Parlay dict with nested legs
            box_scores: Dict of game_id -> player stats

        Returns:
            Settlement result or None if can't settle
        """
        parlay_id = parlay['id']
        legs = parlay.get('nba_sgp_legs', [])

        if not legs:
            logger.warning(f"Parlay {parlay_id[:8]} has no legs")
            return None

        # Find the right box score
        # We need to match the game - for now, search all box scores
        all_player_stats = {}
        for game_stats in box_scores.values():
            all_player_stats.update(game_stats)

        leg_results = []
        for leg in legs:
            leg_result = self._settle_leg(leg, all_player_stats)
            leg_results.append(leg_result)

            # Update leg in database
            self.db.update_leg_result(
                leg_id=leg['id'],
                actual_value=leg_result['actual_value'],
                result=leg_result['result']
            )

        # Determine parlay result
        results = [r['result'] for r in leg_results]

        if all(r == 'VOID' for r in results):
            parlay_result = 'VOID'
        elif any(r == 'LOSS' for r in results):
            parlay_result = 'LOSS'
        elif all(r in ('WIN', 'PUSH', 'VOID') for r in results):
            # All legs hit or pushed/voided - parlay wins
            parlay_result = 'WIN'
        else:
            parlay_result = 'LOSS'

        legs_hit = sum(1 for r in results if r == 'WIN')
        total_legs = len(results)

        # Calculate profit
        combined_odds = parlay.get('combined_odds', 0)
        profit = self._calculate_profit(parlay_result, combined_odds)

        # Create settlement record
        settlement = self.db.settle_parlay(
            parlay_id=parlay_id,
            legs_hit=legs_hit,
            total_legs=total_legs,
            result=parlay_result,
            profit=profit,
        )

        logger.info(
            f"Settled parlay {parlay_id[:8]}: {parlay_result} "
            f"({legs_hit}/{total_legs} legs)"
        )

        return {
            'parlay_id': parlay_id,
            'result': parlay_result,
            'legs_hit': legs_hit,
            'total_legs': total_legs,
            'profit': profit,
        }

    def _settle_leg(
        self,
        leg: Dict,
        player_stats: Dict[str, Dict]
    ) -> Dict:
        """
        Settle a single leg against player stats.

        Args:
            leg: Leg dict with player_name, stat_type, line, direction
            player_stats: Dict of normalized player name -> stats

        Returns:
            Result dict with actual_value and result
        """
        player_name = leg['player_name']
        stat_type = leg['stat_type']
        line = float(leg['line'])
        direction = leg.get('direction', 'over')

        # Find player stats
        normalized = self._normalize_name(player_name)
        stats = player_stats.get(normalized)

        if not stats:
            # Try fuzzy match
            stats = self._fuzzy_match_player(player_name, player_stats)

        if not stats:
            logger.warning(f"Player not found: {player_name}")
            return {'actual_value': None, 'result': 'VOID'}

        # Check if player played
        minutes = stats.get('minutes', 0)
        if minutes == 0:
            logger.info(f"{player_name} DNP - voiding leg")
            return {'actual_value': 0, 'result': 'VOID'}

        # Get actual stat value
        actual = self._get_stat_value(stats, stat_type)

        if actual is None:
            return {'actual_value': None, 'result': 'VOID'}

        # Determine result
        if actual == line:
            result = 'PUSH'
        elif direction == 'over':
            result = 'WIN' if actual > line else 'LOSS'
        else:  # under
            result = 'WIN' if actual < line else 'LOSS'

        logger.debug(
            f"{player_name} {stat_type}: {actual} vs {direction} {line} -> {result}"
        )

        return {'actual_value': actual, 'result': result}

    def _get_stat_value(self, stats: Dict, stat_type: str) -> Optional[float]:
        """Get the stat value for a given stat type."""
        mapping = STAT_MAPPING.get(stat_type)

        if mapping is None:
            logger.warning(f"Unknown stat type: {stat_type}")
            return None

        if isinstance(mapping, list):
            # Combo stat - sum the components
            return sum(stats.get(col, 0) for col in mapping)
        else:
            return stats.get(mapping, 0)

    def _strip_diacritics(self, text: str) -> str:
        """Remove diacritical marks from text (Dončić → Doncic)."""
        import unicodedata
        nfkd = unicodedata.normalize('NFKD', text)
        return ''.join(c for c in nfkd if not unicodedata.combining(c))

    def _normalize_name(self, name: str) -> str:
        """
        Normalize player name for matching.

        Handles diacritics, punctuation, and common variations.
        """
        normalized = name.lower().strip()
        # Strip diacritics (Dončić → Doncic)
        normalized = self._strip_diacritics(normalized)
        # Remove periods and apostrophes
        normalized = normalized.replace('.', '').replace("'", '')
        # Remove suffixes
        for suffix in [' jr', ' iii', ' ii', ' iv', ' sr']:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]
        return normalized.strip()

    def _fuzzy_match_player(
        self,
        player_name: str,
        player_stats: Dict[str, Dict]
    ) -> Optional[Dict]:
        """Try to fuzzy match a player name."""
        normalized = self._normalize_name(player_name)
        parts = normalized.split()

        if len(parts) < 2:
            return None

        # Try last name only
        last_name = parts[-1]
        candidates = [
            stats for name, stats in player_stats.items()
            if last_name in name
        ]

        if len(candidates) == 1:
            return candidates[0]

        # Try first initial + last name
        first_initial = parts[0][0] if parts[0] else ''
        for name, stats in player_stats.items():
            name_parts = name.split()
            if len(name_parts) >= 2:
                if name_parts[-1] == last_name and name_parts[0].startswith(first_initial):
                    return stats

        return None

    def _parse_minutes(self, minutes_str) -> float:
        """Parse minutes string (e.g., '32:15') to float."""
        if not minutes_str:
            return 0

        if isinstance(minutes_str, (int, float)):
            return float(minutes_str)

        try:
            if ':' in str(minutes_str):
                parts = str(minutes_str).split(':')
                return int(parts[0]) + int(parts[1]) / 60
            return float(minutes_str)
        except (ValueError, TypeError):
            return 0

    def _calculate_profit(self, result: str, odds: int) -> float:
        """Calculate profit at $100 stake."""
        if result != 'WIN':
            return -100.0 if result == 'LOSS' else 0.0

        if odds >= 0:
            return odds
        else:
            return 100 * 100 / abs(odds)


# Convenience function
def settle_parlays_for_date(settle_date: date, db_manager=None) -> Dict[str, Any]:
    """
    Settle all parlays for a given date.

    Args:
        settle_date: Date to settle
        db_manager: Optional database manager

    Returns:
        Settlement summary
    """
    engine = SettlementEngine(db_manager)
    return engine.settle_date(settle_date)
