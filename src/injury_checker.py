"""
NBA Injury Checker (STUB)

Placeholder for injury/availability detection.
Will be implemented with pyespn or web scraping in Phase 2.

Current behavior:
- Returns all players as available
- Logs warning about unvalidated availability
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class InjuryStatus(Enum):
    """Player injury/availability status."""
    AVAILABLE = "available"
    QUESTIONABLE = "questionable"
    DOUBTFUL = "doubtful"
    OUT = "out"
    UNKNOWN = "unknown"


@dataclass
class PlayerAvailability:
    """Player availability information."""
    player_name: str
    team: str
    status: InjuryStatus
    injury_type: Optional[str] = None
    notes: Optional[str] = None
    last_updated: Optional[str] = None

    @property
    def is_available(self) -> bool:
        """Check if player is likely to play."""
        return self.status in (InjuryStatus.AVAILABLE, InjuryStatus.QUESTIONABLE)

    @property
    def is_confirmed_out(self) -> bool:
        """Check if player is definitely out."""
        return self.status == InjuryStatus.OUT


class NBAInjuryChecker:
    """
    Stub injury checker for NBA players.

    TODO: Implement with one of:
    - pyespn for ESPN injury data
    - NBA.com official injury report scraping
    - Rotowire API (paid)
    - Manual daily update

    For now, returns all players as available with warnings.
    """

    def __init__(self):
        self._cache: Dict[str, PlayerAvailability] = {}
        self._warned = False

    def _warn_stub(self):
        """Log warning about stub implementation."""
        if not self._warned:
            logger.warning(
                "INJURY CHECKER IS STUBBED - All players returned as available. "
                "This may result in bets on players who are resting/injured. "
                "Implement real injury checking before production use."
            )
            self._warned = True

    def get_player_status(self, player_name: str, team: str = None) -> PlayerAvailability:
        """
        Get player's availability status.

        STUB: Always returns AVAILABLE with warning.

        Args:
            player_name: Player's full name
            team: Team abbreviation (optional)

        Returns:
            PlayerAvailability with status
        """
        self._warn_stub()

        return PlayerAvailability(
            player_name=player_name,
            team=team or "UNK",
            status=InjuryStatus.UNKNOWN,
            injury_type=None,
            notes="STUB: Availability not verified - implement real injury checking",
            last_updated=None
        )

    def get_team_injuries(self, team: str) -> List[PlayerAvailability]:
        """
        Get all injury information for a team.

        STUB: Returns empty list.

        Args:
            team: Team abbreviation

        Returns:
            List of PlayerAvailability for injured players
        """
        self._warn_stub()
        return []

    def is_player_available(self, player_name: str, team: str = None) -> bool:
        """
        Quick check if player is available.

        STUB: Always returns True with warning.

        Args:
            player_name: Player's full name
            team: Team abbreviation (optional)

        Returns:
            True (stubbed - assumes all players available)
        """
        self._warn_stub()
        return True

    def get_rest_candidates(self, team: str, is_b2b: bool = False) -> List[str]:
        """
        Get players likely to rest (load management).

        NBA-specific: Stars often rest on B2Bs or in blowouts.

        STUB: Returns empty list.

        Args:
            team: Team abbreviation
            is_b2b: Whether this is a back-to-back game

        Returns:
            List of player names likely to rest
        """
        self._warn_stub()

        if is_b2b:
            logger.info(
                f"B2B game for {team} - high-value targets may rest. "
                "Check injury report before betting."
            )

        return []

    def refresh(self):
        """
        Refresh injury data from source.

        STUB: No-op.
        """
        self._warn_stub()
        logger.info("Injury refresh called (stubbed - no action taken)")


# =============================================================================
# CONVENIENCE
# =============================================================================

_checker: Optional[NBAInjuryChecker] = None

def get_injury_checker() -> NBAInjuryChecker:
    """Get singleton injury checker instance."""
    global _checker
    if _checker is None:
        _checker = NBAInjuryChecker()
    return _checker
