"""
Base Signal Framework

Defines the abstract base class and data structures for all NBA signals.
Adapted from NHL SGP Engine architecture.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional, Any


@dataclass
class SignalResult:
    """
    Result from a signal calculation.

    Attributes:
        signal_type: Name of the signal ('trend', 'usage', etc.)
        strength: -1.0 to +1.0 (negative=UNDER, positive=OVER)
        confidence: 0.0 to 1.0 (how reliable is this signal)
        evidence: Human-readable explanation
        raw_data: Optional dict with underlying calculations
    """
    signal_type: str
    strength: float  # -1.0 to +1.0
    confidence: float  # 0.0 to 1.0
    evidence: str
    raw_data: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        # Clamp values
        self.strength = max(-1.0, min(1.0, self.strength))
        self.confidence = max(0.0, min(1.0, self.confidence))

    @property
    def direction(self) -> str:
        """Get recommended direction based on strength."""
        return 'over' if self.strength > 0 else 'under'

    @property
    def weighted_strength(self) -> float:
        """Strength weighted by confidence."""
        return self.strength * self.confidence

    def to_dict(self) -> Dict:
        return {
            'signal_type': self.signal_type,
            'strength': self.strength,
            'confidence': self.confidence,
            'evidence': self.evidence,
            'direction': self.direction,
            'raw_data': self.raw_data,
        }


@dataclass
class PropContext:
    """
    Full context for evaluating a player prop.

    Contains all data needed by signals to calculate edges.
    """
    # Player identification
    player_id: int
    player_name: str
    team: str
    team_id: int

    # Prop details
    stat_type: str  # 'points', 'rebounds', 'assists', etc.
    line: float
    over_odds: int = -110
    under_odds: int = -110

    # Season stats
    games_played: int = 0
    minutes_per_game: float = 0.0
    usage_pct: float = 0.0
    season_avg: float = 0.0  # Season average for this stat

    # Recent stats (L5)
    recent_avg: float = 0.0  # L5 average for this stat
    recent_minutes: float = 0.0

    # Opponent context
    opponent_team: str = ''
    opponent_team_id: int = 0
    opponent_def_rating: float = 112.0  # League avg ~112
    opponent_pace: float = 99.0  # League avg ~99

    # Game context
    game_date: str = ''
    is_home: bool = True
    is_b2b: bool = False
    is_3_in_4: bool = False
    game_total: Optional[float] = None
    spread: Optional[float] = None

    # Flags
    is_high_value: bool = False

    def to_dict(self) -> Dict:
        return self.__dict__.copy()


class BaseSignal(ABC):
    """
    Abstract base class for all signals.

    Each signal implements:
    - calculate(): Returns SignalResult for a prop
    - weight: Relative importance in edge calculation
    """

    # Signal weight in edge calculation (should sum to 1.0 across all signals)
    weight: float = 0.0

    # Signal name
    name: str = "base"

    @abstractmethod
    def calculate(self, ctx: PropContext) -> SignalResult:
        """
        Calculate signal for a prop.

        Args:
            ctx: Full prop context with player stats, opponent, game info

        Returns:
            SignalResult with strength, confidence, and evidence
        """
        pass

    def _clamp(self, value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
        """Clamp value to range."""
        return max(min_val, min(max_val, value))


# =============================================================================
# STAT TYPE MAPPINGS
# =============================================================================

# Map stat_type to the player stat field
STAT_TYPE_TO_FIELD = {
    'points': 'pts',
    'rebounds': 'reb',
    'assists': 'ast',
    'threes': 'fg3m',
    'blocks': 'blk',
    'steals': 'stl',
    'turnovers': 'tov',
    'fgm': 'fgm',
    'ftm': 'ftm',
    # Combo props
    'pra': ['pts', 'reb', 'ast'],
    'pr': ['pts', 'reb'],
    'pa': ['pts', 'ast'],
    'ra': ['reb', 'ast'],
    'blocks_steals': ['blk', 'stl'],
}

def get_stat_value(stats: Dict, stat_type: str) -> float:
    """
    Get stat value from stats dict, handling combo props.

    Args:
        stats: Dict with stat values
        stat_type: Stat type key

    Returns:
        Float value (sum for combo props)
    """
    mapping = STAT_TYPE_TO_FIELD.get(stat_type)

    if mapping is None:
        return 0.0

    if isinstance(mapping, list):
        # Combo prop - sum the values
        return sum(stats.get(f, 0) for f in mapping)
    else:
        return stats.get(mapping, 0)
