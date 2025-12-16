"""
NBA Data Provider

Wraps nba_api with caching and provides all data needed for SGP signals:
- Player game logs (trend, usage)
- Team pace and defensive ratings (matchup, correlation)
- Schedule analysis (B2B, 3-in-4 detection)
- High-value target filtering
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import pandas as pd

from nba_api.stats.endpoints import (
    playergamelog,
    leaguedashplayerstats,
    leaguedashteamstats,
    teamgamelog,
    scoreboardv2,
)
from nba_api.stats.static import players, teams

logger = logging.getLogger(__name__)


@dataclass
class PlayerContext:
    """Rich context for a player prop."""
    player_id: int
    player_name: str
    team: str
    team_id: int

    # Season stats
    games_played: int
    minutes_per_game: float
    usage_pct: float

    # Per-game averages
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    fg3m: float
    fgm: float
    ftm: float
    tov: float

    # Recent form (L5)
    pts_l5: float
    reb_l5: float
    ast_l5: float
    min_l5: float

    # Flags
    is_high_value: bool  # MIN >= 25, GP >= 15, USG >= 18%

    def to_dict(self) -> Dict:
        return self.__dict__


@dataclass
class GameContext:
    """Context for a specific game."""
    game_id: str
    game_date: str
    home_team: str
    away_team: str
    home_team_id: int
    away_team_id: int

    # Team stats
    home_pace: float
    away_pace: float
    home_def_rating: float
    away_def_rating: float

    # Schedule context
    home_is_b2b: bool
    away_is_b2b: bool
    home_is_3_in_4: bool
    away_is_3_in_4: bool


class RateLimiter:
    """Rate limiter for nba_api calls."""

    def __init__(self, min_interval: float = 0.6):
        self.min_interval = min_interval
        self.last_call = 0

    def wait(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()


class NBADataProvider:
    """
    Data provider for NBA SGP engine.

    Provides:
    - Player stats and game logs
    - Team pace and defensive ratings
    - Schedule analysis (B2B, 3-in-4)
    - High-value target filtering
    """

    SEASON = '2024-25'

    # Cache TTLs (seconds)
    CACHE_TTL = {
        'player_gamelog': 3600,      # 1 hour
        'league_stats': 3600,        # 1 hour
        'team_stats': 86400,         # 24 hours
        'schedule': 3600,            # 1 hour
    }

    def __init__(self):
        self.rate_limiter = RateLimiter(min_interval=0.6)
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}

        # Static lookups
        self._players_by_name: Dict[str, Dict] = {}
        self._players_by_id: Dict[int, Dict] = {}
        self._teams_by_abbrev: Dict[str, Dict] = {}
        self._teams_by_id: Dict[int, Dict] = {}

        self._init_static_data()

    def _init_static_data(self):
        """Initialize static player and team lookups."""
        for player in players.get_active_players():
            self._players_by_name[player['full_name'].lower()] = player
            self._players_by_id[player['id']] = player

        for team in teams.get_teams():
            self._teams_by_abbrev[team['abbreviation']] = team
            self._teams_by_id[team['id']] = team

        logger.info(f"Loaded {len(self._players_by_name)} players, {len(self._teams_by_abbrev)} teams")

    def _get_cached(self, key: str, ttl_type: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self._cache:
            age = time.time() - self._cache_times.get(key, 0)
            if age < self.CACHE_TTL.get(ttl_type, 3600):
                return self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any):
        """Set cached value."""
        self._cache[key] = value
        self._cache_times[key] = time.time()

    # =========================================================================
    # PLAYER LOOKUPS
    # =========================================================================

    def find_player(self, name: str) -> Optional[Dict]:
        """Find player by name (case-insensitive)."""
        return self._players_by_name.get(name.lower())

    def get_player_by_id(self, player_id: int) -> Optional[Dict]:
        """Get player by ID."""
        return self._players_by_id.get(player_id)

    # =========================================================================
    # TEAM LOOKUPS
    # =========================================================================

    def find_team(self, abbrev: str) -> Optional[Dict]:
        """Find team by abbreviation."""
        return self._teams_by_abbrev.get(abbrev.upper())

    def get_team_by_id(self, team_id: int) -> Optional[Dict]:
        """Get team by ID."""
        return self._teams_by_id.get(team_id)

    # =========================================================================
    # PLAYER GAME LOGS
    # =========================================================================

    def get_player_gamelog(
        self,
        player_id: int,
        season: str = None,
        last_n: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get player game log.

        Args:
            player_id: NBA player ID
            season: Season string (default: current)
            last_n: Limit to last N games

        Returns:
            DataFrame with game-by-game stats
        """
        season = season or self.SEASON
        cache_key = f"gamelog_{player_id}_{season}"

        cached = self._get_cached(cache_key, 'player_gamelog')
        if cached is not None:
            df = cached
        else:
            self.rate_limiter.wait()
            try:
                gamelog = playergamelog.PlayerGameLog(
                    player_id=player_id,
                    season=season,
                    season_type_all_star='Regular Season'
                )
                df = gamelog.get_data_frames()[0]
                self._set_cached(cache_key, df)
            except Exception as e:
                logger.error(f"Error fetching gamelog for {player_id}: {e}")
                return pd.DataFrame()

        if last_n and len(df) > last_n:
            df = df.head(last_n)

        return df

    def get_player_season_stats(self, player_id: int) -> Optional[Dict]:
        """Get player's season averages."""
        df = self.get_player_gamelog(player_id)

        if df.empty:
            return None

        return {
            'games_played': len(df),
            'minutes': df['MIN'].mean(),
            'pts': df['PTS'].mean(),
            'reb': df['REB'].mean(),
            'ast': df['AST'].mean(),
            'stl': df['STL'].mean(),
            'blk': df['BLK'].mean(),
            'fg3m': df['FG3M'].mean(),
            'fgm': df['FGM'].mean(),
            'ftm': df['FTM'].mean(),
            'tov': df['TOV'].mean(),
        }

    def get_player_recent_stats(self, player_id: int, n_games: int = 5) -> Optional[Dict]:
        """Get player's recent averages (last N games)."""
        df = self.get_player_gamelog(player_id, last_n=n_games)

        if df.empty:
            return None

        return {
            'games': len(df),
            'minutes': df['MIN'].mean(),
            'pts': df['PTS'].mean(),
            'reb': df['REB'].mean(),
            'ast': df['AST'].mean(),
            'stl': df['STL'].mean(),
            'blk': df['BLK'].mean(),
            'fg3m': df['FG3M'].mean(),
        }

    # =========================================================================
    # TEAM STATS (PACE, DEFENSE)
    # =========================================================================

    def get_team_stats(self) -> pd.DataFrame:
        """
        Get all team stats including pace and defensive rating.

        Returns:
            DataFrame with TEAM_ID, TEAM_NAME, PACE, DEF_RATING
        """
        cache_key = f"team_stats_{self.SEASON}"

        cached = self._get_cached(cache_key, 'team_stats')
        if cached is not None:
            return cached

        self.rate_limiter.wait()
        try:
            stats = leaguedashteamstats.LeagueDashTeamStats(
                season=self.SEASON,
                per_mode_detailed='PerGame',
                measure_type_detailed_defense='Advanced'
            )
            df = stats.get_data_frames()[0]
            self._set_cached(cache_key, df)
            return df
        except Exception as e:
            logger.error(f"Error fetching team stats: {e}")
            return pd.DataFrame()

    def get_team_pace(self, team_id: int) -> float:
        """Get team's pace (possessions per 48 min)."""
        df = self.get_team_stats()
        if df.empty:
            return 99.0  # League average fallback

        team_row = df[df['TEAM_ID'] == team_id]
        if team_row.empty:
            return 99.0

        return team_row['PACE'].iloc[0]

    def get_team_def_rating(self, team_id: int) -> float:
        """Get team's defensive rating (points allowed per 100 possessions)."""
        df = self.get_team_stats()
        if df.empty:
            return 112.0  # League average fallback

        team_row = df[df['TEAM_ID'] == team_id]
        if team_row.empty:
            return 112.0

        return team_row['DEF_RATING'].iloc[0]

    # =========================================================================
    # HIGH-VALUE TARGET FILTER
    # =========================================================================

    def get_high_value_players(self) -> pd.DataFrame:
        """
        Get players who meet high-value criteria.

        Criteria:
        - MIN >= 25 (starter-level minutes)
        - GP >= 15 (enough sample)
        - USG_PCT >= 18% (meaningful usage)

        Returns:
            DataFrame of high-value players with stats
        """
        cache_key = f"high_value_{self.SEASON}"

        cached = self._get_cached(cache_key, 'league_stats')
        if cached is not None:
            return cached

        # Get base stats
        self.rate_limiter.wait()
        base_stats = leaguedashplayerstats.LeagueDashPlayerStats(
            season=self.SEASON,
            per_mode_detailed='PerGame'
        )
        base_df = base_stats.get_data_frames()[0]

        # Get advanced stats (for usage)
        self.rate_limiter.wait()
        adv_stats = leaguedashplayerstats.LeagueDashPlayerStats(
            season=self.SEASON,
            per_mode_detailed='PerGame',
            measure_type_detailed_defense='Advanced'
        )
        adv_df = adv_stats.get_data_frames()[0]

        # Merge
        merged = base_df.merge(
            adv_df[['PLAYER_ID', 'USG_PCT']],
            on='PLAYER_ID',
            how='left'
        )

        # Apply filters
        high_value = merged[
            (merged['MIN'] >= 25) &
            (merged['GP'] >= 15) &
            (merged['USG_PCT'] >= 0.18)
        ].copy()

        self._set_cached(cache_key, high_value)
        logger.info(f"Found {len(high_value)} high-value players")

        return high_value

    def is_high_value_player(self, player_id: int) -> bool:
        """Check if player meets high-value criteria."""
        hv = self.get_high_value_players()
        return player_id in hv['PLAYER_ID'].values

    # =========================================================================
    # SCHEDULE ANALYSIS
    # =========================================================================

    def get_team_schedule(self, team_id: int) -> pd.DataFrame:
        """Get team's game schedule with rest analysis."""
        cache_key = f"schedule_{team_id}_{self.SEASON}"

        cached = self._get_cached(cache_key, 'schedule')
        if cached is not None:
            return cached

        self.rate_limiter.wait()
        try:
            team_log = teamgamelog.TeamGameLog(
                team_id=team_id,
                season=self.SEASON
            )
            df = team_log.get_data_frames()[0]

            # Parse dates
            df['GAME_DATE_PARSED'] = pd.to_datetime(df['GAME_DATE'], format='%b %d, %Y')
            df = df.sort_values('GAME_DATE_PARSED')

            # Calculate rest days
            df['DAYS_REST'] = df['GAME_DATE_PARSED'].diff().dt.days

            # Detect B2B
            df['IS_B2B'] = df['DAYS_REST'] <= 1

            # Detect 3-in-4
            df['IS_3_IN_4'] = False
            for i in range(2, len(df)):
                window_start = df.iloc[i]['GAME_DATE_PARSED'] - timedelta(days=3)
                games_in_window = df[
                    (df['GAME_DATE_PARSED'] >= window_start) &
                    (df['GAME_DATE_PARSED'] <= df.iloc[i]['GAME_DATE_PARSED'])
                ]
                if len(games_in_window) >= 3:
                    df.iloc[i, df.columns.get_loc('IS_3_IN_4')] = True

            self._set_cached(cache_key, df)
            return df

        except Exception as e:
            logger.error(f"Error fetching schedule for team {team_id}: {e}")
            return pd.DataFrame()

    def is_back_to_back(self, team_id: int, game_date: str) -> bool:
        """Check if game is a back-to-back for team."""
        df = self.get_team_schedule(team_id)
        if df.empty:
            return False

        target_date = pd.to_datetime(game_date)
        game_row = df[df['GAME_DATE_PARSED'].dt.date == target_date.date()]

        if game_row.empty:
            return False

        return game_row['IS_B2B'].iloc[0]

    def is_three_in_four(self, team_id: int, game_date: str) -> bool:
        """Check if game is 3rd game in 4 nights."""
        df = self.get_team_schedule(team_id)
        if df.empty:
            return False

        target_date = pd.to_datetime(game_date)
        game_row = df[df['GAME_DATE_PARSED'].dt.date == target_date.date()]

        if game_row.empty:
            return False

        return game_row['IS_3_IN_4'].iloc[0]

    # =========================================================================
    # TODAY'S GAMES
    # =========================================================================

    def get_todays_games(self, date: str = None) -> List[Dict]:
        """
        Get games for a specific date.

        Args:
            date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            List of game dicts with home/away teams
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        cache_key = f"games_{date}"
        cached = self._get_cached(cache_key, 'schedule')
        if cached is not None:
            return cached

        self.rate_limiter.wait()
        try:
            scoreboard = scoreboardv2.ScoreboardV2(game_date=date)
            df = scoreboard.get_data_frames()[0]

            games = []
            for _, row in df.iterrows():
                home_team = self.get_team_by_id(row['HOME_TEAM_ID'])
                away_team = self.get_team_by_id(row['VISITOR_TEAM_ID'])

                games.append({
                    'game_id': row['GAME_ID'],
                    'game_date': date,
                    'status': row['GAME_STATUS_TEXT'],
                    'home_team': home_team['abbreviation'] if home_team else 'UNK',
                    'away_team': away_team['abbreviation'] if away_team else 'UNK',
                    'home_team_id': row['HOME_TEAM_ID'],
                    'away_team_id': row['VISITOR_TEAM_ID'],
                })

            self._set_cached(cache_key, games)
            return games

        except Exception as e:
            logger.error(f"Error fetching games for {date}: {e}")
            return []

    # =========================================================================
    # PLAYER CONTEXT (FULL ENRICHMENT)
    # =========================================================================

    def get_player_context(self, player_name: str) -> Optional[PlayerContext]:
        """
        Get full player context for SGP analysis.

        Args:
            player_name: Player's full name

        Returns:
            PlayerContext with all stats and flags
        """
        player = self.find_player(player_name)
        if not player:
            logger.warning(f"Player not found: {player_name}")
            return None

        player_id = player['id']

        # Get season stats
        season_stats = self.get_player_season_stats(player_id)
        if not season_stats:
            return None

        # Get recent stats
        recent_stats = self.get_player_recent_stats(player_id, n_games=5)

        # Get usage rate from high-value filter
        hv_df = self.get_high_value_players()
        player_row = hv_df[hv_df['PLAYER_ID'] == player_id]

        usage_pct = 0.0
        is_high_value = False
        team_abbrev = ''
        team_id = 0

        if not player_row.empty:
            usage_pct = player_row['USG_PCT'].iloc[0]
            is_high_value = True
            team_abbrev = player_row['TEAM_ABBREVIATION'].iloc[0]
            team_id = player_row['TEAM_ID'].iloc[0]
        else:
            # Fall back to league stats for non-high-value players
            self.rate_limiter.wait()
            all_stats = leaguedashplayerstats.LeagueDashPlayerStats(
                season=self.SEASON,
                per_mode_detailed='PerGame'
            )
            all_df = all_stats.get_data_frames()[0]
            player_row = all_df[all_df['PLAYER_ID'] == player_id]
            if not player_row.empty:
                team_abbrev = player_row['TEAM_ABBREVIATION'].iloc[0]
                team_id = player_row['TEAM_ID'].iloc[0]

        return PlayerContext(
            player_id=player_id,
            player_name=player_name,
            team=team_abbrev,
            team_id=team_id,
            games_played=season_stats['games_played'],
            minutes_per_game=season_stats['minutes'],
            usage_pct=usage_pct,
            pts=season_stats['pts'],
            reb=season_stats['reb'],
            ast=season_stats['ast'],
            stl=season_stats['stl'],
            blk=season_stats['blk'],
            fg3m=season_stats['fg3m'],
            fgm=season_stats['fgm'],
            ftm=season_stats['ftm'],
            tov=season_stats['tov'],
            pts_l5=recent_stats['pts'] if recent_stats else season_stats['pts'],
            reb_l5=recent_stats['reb'] if recent_stats else season_stats['reb'],
            ast_l5=recent_stats['ast'] if recent_stats else season_stats['ast'],
            min_l5=recent_stats['minutes'] if recent_stats else season_stats['minutes'],
            is_high_value=is_high_value,
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_provider: Optional[NBADataProvider] = None


def get_data_provider() -> NBADataProvider:
    """Get singleton data provider instance."""
    global _provider
    if _provider is None:
        _provider = NBADataProvider()
    return _provider


# Alias for backwards compatibility
get_provider = get_data_provider
