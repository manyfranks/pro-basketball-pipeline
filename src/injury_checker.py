"""
NBA Injury Checker

Fetches injury/availability data from ESPN's public API.
Provides player status checks for the SGP engine.

Data Source: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import requests

logger = logging.getLogger(__name__)


class InjuryStatus(Enum):
    """Player injury/availability status."""
    AVAILABLE = "available"
    DAY_TO_DAY = "day-to-day"      # GTD equivalent
    QUESTIONABLE = "questionable"
    DOUBTFUL = "doubtful"
    OUT = "out"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"

    @classmethod
    def from_espn_status(cls, status: str) -> 'InjuryStatus':
        """Convert ESPN status string to InjuryStatus enum."""
        status_lower = status.lower().strip() if status else ""

        mapping = {
            'out': cls.OUT,
            'day-to-day': cls.DAY_TO_DAY,
            'questionable': cls.QUESTIONABLE,
            'doubtful': cls.DOUBTFUL,
            'probable': cls.AVAILABLE,  # Probable = likely to play
            'suspended': cls.SUSPENDED,
        }

        return mapping.get(status_lower, cls.UNKNOWN)


@dataclass
class PlayerAvailability:
    """Player availability information."""
    player_name: str
    team: str
    status: InjuryStatus
    espn_player_id: Optional[str] = None
    injury_type: Optional[str] = None       # e.g., "Knee", "Ankle"
    injury_detail: Optional[str] = None     # e.g., "Sprain"
    return_date: Optional[str] = None       # Expected return date
    short_comment: Optional[str] = None     # Brief injury note
    long_comment: Optional[str] = None      # Detailed injury report
    last_updated: Optional[str] = None

    @property
    def is_available(self) -> bool:
        """Check if player is likely to play."""
        return self.status in (InjuryStatus.AVAILABLE, InjuryStatus.DAY_TO_DAY)

    @property
    def is_confirmed_out(self) -> bool:
        """Check if player is definitely out."""
        return self.status in (InjuryStatus.OUT, InjuryStatus.SUSPENDED)

    @property
    def is_game_time_decision(self) -> bool:
        """Check if player is a game-time decision."""
        return self.status == InjuryStatus.DAY_TO_DAY

    @property
    def confidence_modifier(self) -> float:
        """
        Return a confidence modifier based on injury status.

        Used to reduce signal confidence for uncertain availability.
        """
        modifiers = {
            InjuryStatus.AVAILABLE: 1.0,
            InjuryStatus.DAY_TO_DAY: 0.6,      # Significant uncertainty
            InjuryStatus.QUESTIONABLE: 0.5,
            InjuryStatus.DOUBTFUL: 0.3,
            InjuryStatus.OUT: 0.0,             # Skip entirely
            InjuryStatus.SUSPENDED: 0.0,
            InjuryStatus.UNKNOWN: 0.9,         # Assume available if not on list
        }
        return modifiers.get(self.status, 0.9)

    def to_dict(self) -> Dict:
        return {
            'player_name': self.player_name,
            'team': self.team,
            'status': self.status.value,
            'espn_player_id': self.espn_player_id,
            'injury_type': self.injury_type,
            'injury_detail': self.injury_detail,
            'return_date': self.return_date,
            'short_comment': self.short_comment,
            'is_available': self.is_available,
            'is_confirmed_out': self.is_confirmed_out,
            'confidence_modifier': self.confidence_modifier,
            'last_updated': self.last_updated,
        }


class NBAInjuryChecker:
    """
    Injury checker for NBA players using ESPN's public API.

    Features:
    - Fetches all NBA injuries from ESPN
    - Caches results for 30 minutes
    - Name matching with fuzzy search
    - Team filtering
    """

    ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

    # Cache TTL in seconds (30 minutes)
    CACHE_TTL = 1800

    def __init__(self):
        self._cache: Dict[str, PlayerAvailability] = {}
        self._cache_by_team: Dict[str, List[PlayerAvailability]] = {}
        self._cache_time: float = 0
        self._all_injuries: List[PlayerAvailability] = []

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        return (time.time() - self._cache_time) < self.CACHE_TTL

    def _normalize_name(self, name: str) -> str:
        """Normalize player name for matching."""
        if not name:
            return ""
        # Lowercase and strip
        name = name.lower().strip()
        # Remove common suffixes
        for suffix in [' jr.', ' jr', ' iii', ' ii', ' iv', ' sr.', ' sr']:
            name = name.replace(suffix, '')
        return name

    def _fetch_injuries(self) -> bool:
        """
        Fetch injury data from ESPN API.

        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.get(self.ESPN_INJURIES_URL, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(f"Error fetching ESPN injuries: {e}")
            return False
        except ValueError as e:
            logger.error(f"Error parsing ESPN injuries response: {e}")
            return False

        # Clear caches
        self._cache.clear()
        self._cache_by_team.clear()
        self._all_injuries.clear()

        # Parse injuries
        for team_data in data.get('injuries', []):
            # The parent team_data.displayName is the team name, but we'll use
            # each athlete's actual team abbreviation for proper categorization
            fallback_team = team_data.get('displayName', 'Unknown')[:3].upper()

            for injury in team_data.get('injuries', []):
                availability = self._parse_injury(injury, fallback_team)
                if availability:
                    # Cache by normalized name
                    name_key = self._normalize_name(availability.player_name)
                    self._cache[name_key] = availability

                    # Cache by team (using the player's actual team)
                    player_team = availability.team
                    if player_team not in self._cache_by_team:
                        self._cache_by_team[player_team] = []
                    self._cache_by_team[player_team].append(availability)

                    # Add to all injuries list
                    self._all_injuries.append(availability)

        self._cache_time = time.time()
        logger.info(f"Fetched {len(self._all_injuries)} injuries from ESPN")
        return True

    def _parse_injury(self, injury: Dict, fallback_team: str) -> Optional[PlayerAvailability]:
        """Parse a single injury entry from ESPN API."""
        try:
            athlete = injury.get('athlete', {})
            player_name = athlete.get('displayName', '')

            if not player_name:
                return None

            # Get team abbreviation from the athlete's team data (not the parent)
            team_info = athlete.get('team', {})
            team_abbrev = team_info.get('abbreviation', fallback_team)

            # Get status
            status_str = injury.get('status', 'Unknown')
            status = InjuryStatus.from_espn_status(status_str)

            # Get injury details
            details = injury.get('details', {})
            injury_type = details.get('type', '')
            injury_detail = details.get('detail', '')
            return_date = details.get('returnDate', '')

            # Get comments
            short_comment = injury.get('shortComment', '')
            long_comment = injury.get('longComment', '')

            # Get update timestamp
            last_updated = injury.get('date', '')

            # Get ESPN player ID
            espn_id = injury.get('id', '')

            return PlayerAvailability(
                player_name=player_name,
                team=team_abbrev,
                status=status,
                espn_player_id=espn_id,
                injury_type=injury_type if injury_type else None,
                injury_detail=injury_detail if injury_detail else None,
                return_date=return_date if return_date else None,
                short_comment=short_comment if short_comment else None,
                long_comment=long_comment if long_comment else None,
                last_updated=last_updated if last_updated else None,
            )
        except Exception as e:
            logger.warning(f"Error parsing injury entry: {e}")
            return None

    def refresh(self) -> bool:
        """
        Force refresh of injury data from ESPN.

        Returns:
            True if successful, False otherwise
        """
        logger.info("Refreshing injury data from ESPN...")
        return self._fetch_injuries()

    def _ensure_data(self):
        """Ensure we have valid cached data."""
        if not self._is_cache_valid() or not self._cache:
            self._fetch_injuries()

    def get_player_status(self, player_name: str, team: str = None) -> PlayerAvailability:
        """
        Get player's availability status.

        Args:
            player_name: Player's full name (e.g., "LeBron James")
            team: Team abbreviation (optional, for disambiguation)

        Returns:
            PlayerAvailability with status
        """
        self._ensure_data()

        # Normalize the search name
        name_key = self._normalize_name(player_name)

        # Check cache
        if name_key in self._cache:
            result = self._cache[name_key]
            # If team specified, verify it matches
            if team and result.team != team.upper():
                logger.debug(f"Team mismatch for {player_name}: {result.team} vs {team}")
            return result

        # Try partial match
        for cached_name, availability in self._cache.items():
            if name_key in cached_name or cached_name in name_key:
                if team is None or availability.team == team.upper():
                    logger.debug(f"Partial match: {player_name} -> {availability.player_name}")
                    return availability

        # Player not found in injury list - assume available
        return PlayerAvailability(
            player_name=player_name,
            team=team.upper() if team else "UNK",
            status=InjuryStatus.AVAILABLE,
            short_comment="Not on injury report",
        )

    def get_team_injuries(self, team: str) -> List[PlayerAvailability]:
        """
        Get all injury information for a team.

        Args:
            team: Team abbreviation (e.g., "LAL", "BOS")

        Returns:
            List of PlayerAvailability for injured players
        """
        self._ensure_data()

        team_upper = team.upper()
        return self._cache_by_team.get(team_upper, [])

    def get_all_injuries(self) -> List[PlayerAvailability]:
        """
        Get all current NBA injuries.

        Returns:
            List of all PlayerAvailability entries
        """
        self._ensure_data()
        return self._all_injuries.copy()

    def is_player_available(self, player_name: str, team: str = None) -> bool:
        """
        Quick check if player is available.

        Args:
            player_name: Player's full name
            team: Team abbreviation (optional)

        Returns:
            True if player is likely to play
        """
        status = self.get_player_status(player_name, team)
        return status.is_available

    def is_player_out(self, player_name: str, team: str = None) -> bool:
        """
        Quick check if player is confirmed out.

        Args:
            player_name: Player's full name
            team: Team abbreviation (optional)

        Returns:
            True if player is definitely out
        """
        status = self.get_player_status(player_name, team)
        return status.is_confirmed_out

    def get_rest_candidates(self, team: str, is_b2b: bool = False) -> List[str]:
        """
        Get players likely to rest (load management).

        Args:
            team: Team abbreviation
            is_b2b: Whether this is a back-to-back game

        Returns:
            List of player names who might rest
        """
        self._ensure_data()

        # Get Day-to-Day players for this team
        team_injuries = self.get_team_injuries(team)
        candidates = []

        for inj in team_injuries:
            # Day-to-Day players are rest candidates
            if inj.status == InjuryStatus.DAY_TO_DAY:
                candidates.append(inj.player_name)
            # On B2B, players with recent injuries may also rest
            elif is_b2b and inj.return_date:
                candidates.append(inj.player_name)

        if is_b2b and not candidates:
            logger.info(
                f"B2B game for {team} - check for load management rest. "
                "Star players may sit even if not on injury report."
            )

        return candidates

    def get_players_by_status(self, status: InjuryStatus) -> List[PlayerAvailability]:
        """
        Get all players with a specific status.

        Args:
            status: InjuryStatus to filter by

        Returns:
            List of PlayerAvailability with matching status
        """
        self._ensure_data()
        return [p for p in self._all_injuries if p.status == status]

    def get_injury_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all current injuries.

        Returns:
            Dict with counts by status and team
        """
        self._ensure_data()

        summary = {
            'total': len(self._all_injuries),
            'by_status': {},
            'by_team': {},
            'last_updated': datetime.fromtimestamp(self._cache_time).isoformat()
        }

        for inj in self._all_injuries:
            # Count by status
            status_key = inj.status.value
            summary['by_status'][status_key] = summary['by_status'].get(status_key, 0) + 1

            # Count by team
            summary['by_team'][inj.team] = summary['by_team'].get(inj.team, 0) + 1

        return summary


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_checker: Optional[NBAInjuryChecker] = None


def get_injury_checker() -> NBAInjuryChecker:
    """Get singleton injury checker instance."""
    global _checker
    if _checker is None:
        _checker = NBAInjuryChecker()
    return _checker
