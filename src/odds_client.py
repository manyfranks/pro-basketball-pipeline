"""
NBA Odds Client

Fetches player props and game lines from The Odds API for NBA games.
Supports:
- Player props (points, rebounds, assists, threes, etc.)
- Alternate lines
- Game totals and spreads (for correlation signal)
"""

import logging
import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import requests

logger = logging.getLogger(__name__)


# =============================================================================
# MARKET DEFINITIONS (from Odds API docs)
# =============================================================================

# Primary player props
NBA_PLAYER_PROP_MARKETS = [
    'player_points',
    'player_rebounds',
    'player_assists',
    'player_threes',
    'player_blocks',
    'player_steals',
    'player_blocks_steals',
    'player_turnovers',
    'player_points_rebounds_assists',
    'player_points_rebounds',
    'player_points_assists',
    'player_rebounds_assists',
    'player_field_goals',
    'player_frees_made',
    'player_double_double',
    'player_triple_double',
]

# Alternate lines (X+ markets)
NBA_ALTERNATE_MARKETS = [
    'player_points_alternate',
    'player_rebounds_alternate',
    'player_assists_alternate',
    'player_threes_alternate',
    'player_blocks_alternate',
    'player_steals_alternate',
]

# Game lines (for correlation signal)
NBA_GAME_MARKETS = [
    'h2h',       # Moneyline
    'spreads',   # Point spread
    'totals',    # Game total (over/under)
]


@dataclass
class PropLine:
    """A single prop line from Odds API."""
    player_name: str
    stat_type: str          # 'points', 'rebounds', 'assists', etc.
    line: float
    over_odds: int          # American odds
    under_odds: int
    bookmaker: str
    last_update: str

    @property
    def over_implied_prob(self) -> float:
        """Convert over odds to implied probability."""
        if self.over_odds >= 0:
            return 100 / (self.over_odds + 100)
        else:
            return abs(self.over_odds) / (abs(self.over_odds) + 100)

    @property
    def under_implied_prob(self) -> float:
        """Convert under odds to implied probability."""
        if self.under_odds >= 0:
            return 100 / (self.under_odds + 100)
        else:
            return abs(self.under_odds) / (abs(self.under_odds) + 100)


@dataclass
class GameLine:
    """Game-level betting line."""
    game_id: str
    home_team: str
    away_team: str
    spread: float           # Home team spread (negative = favorite)
    total: float            # Over/under
    home_ml: int            # Home moneyline
    away_ml: int            # Away moneyline
    bookmaker: str


class NBAOddsClient:
    """
    Client for fetching NBA odds from The Odds API.

    Features:
    - Player props with featured and alternate lines
    - Game totals and spreads
    - Response caching (24hr for historical, 1hr for live)
    - Rate limiting
    """

    BASE_URL = "https://api.the-odds-api.com/v4"
    SPORT = "basketball_nba"

    # Cache directory
    CACHE_DIR = Path(__file__).parent.parent / "data" / "odds_cache"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get('ODDS_API_KEY')
        if not self.api_key:
            logger.warning("ODDS_API_KEY not set - API calls will fail")

        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._last_request = 0
        self._min_interval = 1.0  # 1 second between requests

    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Get cache file path for a key."""
        return self.CACHE_DIR / f"{cache_key}.json"

    def _get_cached(self, cache_key: str, max_age_hours: int = 1) -> Optional[Any]:
        """Get cached response if not expired."""
        cache_path = self._get_cache_path(cache_key)

        if not cache_path.exists():
            return None

        # Check age
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        age = datetime.now() - mtime

        if age > timedelta(hours=max_age_hours):
            return None

        try:
            with open(cache_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Cache read error: {e}")
            return None

    def _set_cached(self, cache_key: str, data: Any):
        """Save response to cache."""
        cache_path = self._get_cache_path(cache_key)
        try:
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Cache write error: {e}")

    # =========================================================================
    # API METHODS
    # =========================================================================

    def get_events(self) -> List[Dict]:
        """Get upcoming NBA events (games)."""
        cache_key = f"nba_events_{datetime.now().strftime('%Y%m%d')}"
        cached = self._get_cached(cache_key, max_age_hours=1)
        if cached:
            return cached

        self._rate_limit()

        url = f"{self.BASE_URL}/sports/{self.SPORT}/events"
        params = {'apiKey': self.api_key}

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            self._set_cached(cache_key, data)
            logger.info(f"Fetched {len(data)} NBA events")
            return data
        except Exception as e:
            logger.error(f"Error fetching events: {e}")
            return []

    def get_game_odds(self, event_id: str) -> Optional[Dict]:
        """
        Get game-level odds (spread, total, moneyline).

        Args:
            event_id: Odds API event ID

        Returns:
            Dict with spread, total, moneylines
        """
        cache_key = f"game_odds_{event_id}"
        cached = self._get_cached(cache_key, max_age_hours=1)
        if cached:
            return cached

        self._rate_limit()

        url = f"{self.BASE_URL}/sports/{self.SPORT}/events/{event_id}/odds"
        params = {
            'apiKey': self.api_key,
            'regions': 'us',
            'markets': ','.join(NBA_GAME_MARKETS),
            'oddsFormat': 'american',
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            self._set_cached(cache_key, data)
            return data
        except Exception as e:
            logger.error(f"Error fetching game odds for {event_id}: {e}")
            return None

    def get_player_props(
        self,
        event_id: str,
        markets: List[str] = None,
        include_alternates: bool = False
    ) -> List[PropLine]:
        """
        Get player props for a specific event.

        Args:
            event_id: Odds API event ID
            markets: List of market keys (default: primary props)
            include_alternates: Include alternate lines

        Returns:
            List of PropLine objects
        """
        if markets is None:
            markets = NBA_PLAYER_PROP_MARKETS.copy()

        if include_alternates:
            markets.extend(NBA_ALTERNATE_MARKETS)

        cache_key = f"props_{event_id}_{'_'.join(sorted(markets)[:3])}"
        cached = self._get_cached(cache_key, max_age_hours=1)
        if cached:
            return [PropLine(**p) for p in cached]

        self._rate_limit()

        url = f"{self.BASE_URL}/sports/{self.SPORT}/events/{event_id}/odds"
        params = {
            'apiKey': self.api_key,
            'regions': 'us',
            'markets': ','.join(markets),
            'oddsFormat': 'american',
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"Error fetching props for {event_id}: {e}")
            return []

        # Parse props from response
        props = self._parse_props_response(data)

        # Cache the parsed props
        self._set_cached(cache_key, [p.__dict__ for p in props])

        return props

    def _parse_props_response(self, data: Dict) -> List[PropLine]:
        """Parse Odds API response into PropLine objects."""
        props = []

        if not data or 'bookmakers' not in data:
            return props

        for bookmaker in data.get('bookmakers', []):
            bk_name = bookmaker.get('key', 'unknown')

            for market in bookmaker.get('markets', []):
                market_key = market.get('key', '')
                stat_type = self._market_to_stat_type(market_key)

                if not stat_type:
                    continue

                # Group outcomes by description (player name + line)
                outcomes_by_player = {}

                for outcome in market.get('outcomes', []):
                    player_name = outcome.get('description', '')
                    point = outcome.get('point', 0)
                    name = outcome.get('name', '')  # 'Over' or 'Under'
                    price = outcome.get('price', -110)

                    key = (player_name, point)
                    if key not in outcomes_by_player:
                        outcomes_by_player[key] = {'over': None, 'under': None}

                    if name == 'Over':
                        outcomes_by_player[key]['over'] = price
                    elif name == 'Under':
                        outcomes_by_player[key]['under'] = price

                # Create PropLine for each player/line combination
                for (player_name, line), odds in outcomes_by_player.items():
                    if odds['over'] is not None and odds['under'] is not None:
                        props.append(PropLine(
                            player_name=player_name,
                            stat_type=stat_type,
                            line=line,
                            over_odds=odds['over'],
                            under_odds=odds['under'],
                            bookmaker=bk_name,
                            last_update=data.get('last_update', ''),
                        ))

        logger.info(f"Parsed {len(props)} prop lines")
        return props

    def _market_to_stat_type(self, market_key: str) -> Optional[str]:
        """Convert Odds API market key to stat type."""
        mapping = {
            'player_points': 'points',
            'player_points_alternate': 'points',
            'player_rebounds': 'rebounds',
            'player_rebounds_alternate': 'rebounds',
            'player_assists': 'assists',
            'player_assists_alternate': 'assists',
            'player_threes': 'threes',
            'player_threes_alternate': 'threes',
            'player_blocks': 'blocks',
            'player_blocks_alternate': 'blocks',
            'player_steals': 'steals',
            'player_steals_alternate': 'steals',
            'player_blocks_steals': 'blocks_steals',
            'player_turnovers': 'turnovers',
            'player_turnovers_alternate': 'turnovers',
            'player_points_rebounds_assists': 'pra',
            'player_points_rebounds_assists_alternate': 'pra',
            'player_points_rebounds': 'pr',
            'player_points_rebounds_alternate': 'pr',
            'player_points_assists': 'pa',
            'player_points_assists_alternate': 'pa',
            'player_rebounds_assists': 'ra',
            'player_rebounds_assists_alternate': 'ra',
            'player_field_goals': 'fgm',
            'player_frees_made': 'ftm',
            'player_double_double': 'double_double',
            'player_triple_double': 'triple_double',
        }
        return mapping.get(market_key)

    def parse_game_line(self, data: Dict) -> Optional[GameLine]:
        """Parse game-level odds into GameLine object."""
        if not data or 'bookmakers' not in data:
            return None

        home_team = data.get('home_team', '')
        away_team = data.get('away_team', '')
        game_id = data.get('id', '')

        spread = None
        total = None
        home_ml = None
        away_ml = None
        bookmaker = None

        for bk in data.get('bookmakers', []):
            bookmaker = bk.get('key')

            for market in bk.get('markets', []):
                key = market.get('key')
                outcomes = market.get('outcomes', [])

                if key == 'spreads':
                    for outcome in outcomes:
                        if outcome.get('name') == home_team:
                            spread = outcome.get('point', 0)
                            break

                elif key == 'totals':
                    for outcome in outcomes:
                        if outcome.get('name') == 'Over':
                            total = outcome.get('point', 0)
                            break

                elif key == 'h2h':
                    for outcome in outcomes:
                        if outcome.get('name') == home_team:
                            home_ml = outcome.get('price', 0)
                        elif outcome.get('name') == away_team:
                            away_ml = outcome.get('price', 0)

            # Use first bookmaker with complete data
            if spread is not None and total is not None:
                break

        if spread is None or total is None:
            return None

        return GameLine(
            game_id=game_id,
            home_team=home_team,
            away_team=away_team,
            spread=spread,
            total=total,
            home_ml=home_ml or 0,
            away_ml=away_ml or 0,
            bookmaker=bookmaker or 'unknown',
        )

    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================

    # Team name to abbreviation mapping
    TEAM_ABBREV = {
        'Atlanta Hawks': 'ATL',
        'Boston Celtics': 'BOS',
        'Brooklyn Nets': 'BKN',
        'Charlotte Hornets': 'CHA',
        'Chicago Bulls': 'CHI',
        'Cleveland Cavaliers': 'CLE',
        'Dallas Mavericks': 'DAL',
        'Denver Nuggets': 'DEN',
        'Detroit Pistons': 'DET',
        'Golden State Warriors': 'GSW',
        'Houston Rockets': 'HOU',
        'Indiana Pacers': 'IND',
        'Los Angeles Clippers': 'LAC',
        'Los Angeles Lakers': 'LAL',
        'Memphis Grizzlies': 'MEM',
        'Miami Heat': 'MIA',
        'Milwaukee Bucks': 'MIL',
        'Minnesota Timberwolves': 'MIN',
        'New Orleans Pelicans': 'NOP',
        'New York Knicks': 'NYK',
        'Oklahoma City Thunder': 'OKC',
        'Orlando Magic': 'ORL',
        'Philadelphia 76ers': 'PHI',
        'Phoenix Suns': 'PHX',
        'Portland Trail Blazers': 'POR',
        'Sacramento Kings': 'SAC',
        'San Antonio Spurs': 'SAS',
        'Toronto Raptors': 'TOR',
        'Utah Jazz': 'UTA',
        'Washington Wizards': 'WAS',
    }

    def _get_team_abbrev(self, team_name: str) -> str:
        """Convert full team name to abbreviation."""
        return self.TEAM_ABBREV.get(team_name, team_name[:3].upper())

    def get_todays_games(self) -> List[Dict]:
        """
        Get today's NBA games with odds data.

        Returns:
            List of game dicts with:
            - id: Event ID
            - home_team: Home team abbreviation (e.g., 'NYK')
            - away_team: Away team abbreviation (e.g., 'SAS')
            - home_team_full: Full team name
            - away_team_full: Full team name
            - commence_time: Game start time (ISO format)
            - game_line: GameLine object (spread, total, moneylines)
        """
        from zoneinfo import ZoneInfo
        ET = ZoneInfo('America/New_York')

        events = self.get_events()

        # Filter to today's events (in ET)
        today = datetime.now(ET).date()
        todays_events = []

        for e in events:
            try:
                commence = datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00'))
                if commence.astimezone(ET).date() == today:
                    todays_events.append(e)
            except Exception:
                continue

        logger.info(f"Found {len(todays_events)} games for today ({today})")

        # Enrich with game lines
        games = []
        for event in todays_events:
            event_id = event['id']
            home_full = event.get('home_team', '')
            away_full = event.get('away_team', '')

            # Fetch game odds
            odds_data = self.get_game_odds(event_id)
            game_line = self.parse_game_line(odds_data) if odds_data else None

            game = {
                'id': event_id,
                'home_team': self._get_team_abbrev(home_full),
                'away_team': self._get_team_abbrev(away_full),
                'home_team_full': home_full,
                'away_team_full': away_full,
                'commence_time': event.get('commence_time', ''),
                'game_line': game_line,
            }

            # Add spread/total for convenience
            if game_line:
                game['spread'] = game_line.spread
                game['total'] = game_line.total

            games.append(game)

        return games

    def get_todays_props(self, stat_types: List[str] = None) -> Dict[str, List[PropLine]]:
        """
        Get all player props for today's games.

        Args:
            stat_types: Filter by stat types (default: all)

        Returns:
            Dict mapping game_id to list of props
        """
        events = self.get_events()

        # Filter to today's events
        today = datetime.now().date()
        todays_events = [
            e for e in events
            if datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00')).date() == today
        ]

        logger.info(f"Found {len(todays_events)} events for today")

        all_props = {}
        for event in todays_events:
            event_id = event['id']
            props = self.get_player_props(event_id)

            if stat_types:
                props = [p for p in props if p.stat_type in stat_types]

            all_props[event_id] = props

        return all_props


# =============================================================================
# CONVENIENCE
# =============================================================================

_client: Optional[NBAOddsClient] = None

def get_odds_client() -> NBAOddsClient:
    """Get singleton odds client instance."""
    global _client
    if _client is None:
        _client = NBAOddsClient()
    return _client
