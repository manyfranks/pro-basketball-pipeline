"""
NBA SGP Edge Calculator

Aggregates signals to calculate edge on player props.
Follows the NHL SGP Engine pattern - market-first philosophy.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from .signals import (
    PropContext,
    SignalResult,
    ALL_SIGNALS,
    LineValueSignal,
    TrendSignal,
    UsageSignal,
    MatchupSignal,
    EnvironmentSignal,
    CorrelationSignal,
)

logger = logging.getLogger(__name__)


@dataclass
class EdgeResult:
    """
    Result of edge calculation for a prop.

    Contains:
    - Overall edge score and direction
    - Confidence level
    - Individual signal breakdowns
    - Recommendation
    """
    # Core result
    player_name: str
    stat_type: str
    line: float
    edge_score: float           # -1.0 to +1.0 (weighted signal average)
    confidence: float           # 0.0 to 1.0
    direction: str              # 'over' or 'under'

    # Signal breakdown
    signals: List[SignalResult] = field(default_factory=list)

    # Recommendation
    recommendation: str = ''    # 'strong_over', 'lean_over', 'pass', etc.
    expected_value: float = 0.0

    # Context
    is_high_value: bool = False
    over_odds: int = -110
    under_odds: int = -110

    def to_dict(self) -> Dict:
        return {
            'player_name': self.player_name,
            'stat_type': self.stat_type,
            'line': self.line,
            'edge_score': round(self.edge_score, 4),
            'confidence': round(self.confidence, 4),
            'direction': self.direction,
            'recommendation': self.recommendation,
            'expected_value': round(self.expected_value, 4),
            'is_high_value': self.is_high_value,
            'over_odds': self.over_odds,
            'under_odds': self.under_odds,
            'signals': [s.to_dict() for s in self.signals],
        }


class EdgeCalculator:
    """
    Calculates edge on NBA player props using signal framework.

    Signal weights (must sum to 1.0):
    - Line Value: 30% (core signal)
    - Trend: 20%
    - Usage: 20%
    - Matchup: 15%
    - Environment: 10%
    - Correlation: 5%

    Philosophy:
    - Trust market lines as baseline
    - Detect edges where data disagrees with market
    - Weight recent performance, high-value players
    """

    # Edge thresholds for recommendations
    STRONG_EDGE = 0.25       # Strong recommendation
    MODERATE_EDGE = 0.15     # Lean recommendation
    MIN_EDGE = 0.08          # Minimum to consider

    # Minimum confidence for any recommendation
    MIN_CONFIDENCE = 0.40

    def __init__(self):
        """Initialize with all signals."""
        self.signals = [
            LineValueSignal(),
            TrendSignal(),
            UsageSignal(),
            MatchupSignal(),
            EnvironmentSignal(),
            CorrelationSignal(),
        ]

        # Verify weights sum to 1.0
        total_weight = sum(s.weight for s in self.signals)
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(f"Signal weights sum to {total_weight}, not 1.0")

    def calculate_edge(self, ctx: PropContext) -> EdgeResult:
        """
        Calculate edge for a player prop.

        Args:
            ctx: Full prop context

        Returns:
            EdgeResult with edge score, direction, and recommendation
        """
        # Run all signals
        signal_results = []
        for signal in self.signals:
            try:
                result = signal.calculate(ctx)
                signal_results.append(result)
            except Exception as e:
                logger.error(f"Error in {signal.name} signal: {e}")
                # Append neutral result on error
                signal_results.append(SignalResult(
                    signal_type=signal.name,
                    strength=0.0,
                    confidence=0.0,
                    evidence=f"Error: {e}",
                ))

        # Calculate weighted edge score
        total_weighted_strength = 0.0
        total_weighted_confidence = 0.0
        total_weight = 0.0

        for signal, result in zip(self.signals, signal_results):
            weighted_strength = result.strength * signal.weight
            weighted_confidence = result.confidence * signal.weight

            total_weighted_strength += weighted_strength
            total_weighted_confidence += weighted_confidence
            total_weight += signal.weight

        # Normalize
        if total_weight > 0:
            edge_score = total_weighted_strength  # Already weighted
            confidence = total_weighted_confidence / total_weight
        else:
            edge_score = 0.0
            confidence = 0.0

        # Determine direction
        direction = 'over' if edge_score > 0 else 'under'

        # Calculate recommendation
        recommendation = self._get_recommendation(edge_score, confidence, ctx)

        # Calculate expected value
        odds = ctx.over_odds if direction == 'over' else ctx.under_odds
        expected_value = self._calculate_ev(abs(edge_score), confidence, odds)

        return EdgeResult(
            player_name=ctx.player_name,
            stat_type=ctx.stat_type,
            line=ctx.line,
            edge_score=edge_score,
            confidence=confidence,
            direction=direction,
            signals=signal_results,
            recommendation=recommendation,
            expected_value=expected_value,
            is_high_value=ctx.is_high_value,
            over_odds=ctx.over_odds,
            under_odds=ctx.under_odds,
        )

    def _get_recommendation(
        self,
        edge_score: float,
        confidence: float,
        ctx: PropContext
    ) -> str:
        """
        Generate recommendation based on edge and confidence.

        Returns one of:
        - 'strong_over', 'strong_under'
        - 'lean_over', 'lean_under'
        - 'slight_over', 'slight_under'
        - 'pass'
        """
        abs_edge = abs(edge_score)
        direction = 'over' if edge_score > 0 else 'under'

        # Must meet minimum confidence
        if confidence < self.MIN_CONFIDENCE:
            return 'pass'

        # Must meet minimum edge
        if abs_edge < self.MIN_EDGE:
            return 'pass'

        # Strong edge
        if abs_edge >= self.STRONG_EDGE and confidence >= 0.55:
            return f'strong_{direction}'

        # Moderate edge
        if abs_edge >= self.MODERATE_EDGE and confidence >= 0.50:
            return f'lean_{direction}'

        # Slight edge (high value players only)
        if abs_edge >= self.MIN_EDGE and ctx.is_high_value:
            return f'slight_{direction}'

        return 'pass'

    def _calculate_ev(
        self,
        edge_magnitude: float,
        confidence: float,
        odds: int
    ) -> float:
        """
        Calculate simple expected value.

        This is simplified - actual EV would need true probability estimation.
        """
        # Convert odds to implied probability
        if odds >= 0:
            implied_prob = 100 / (odds + 100)
        else:
            implied_prob = abs(odds) / (abs(odds) + 100)

        # Our estimated probability (implied + edge)
        est_prob = implied_prob + (edge_magnitude * confidence * 0.1)
        est_prob = max(0.01, min(0.99, est_prob))

        # Calculate decimal odds
        if odds >= 0:
            decimal_odds = 1 + odds / 100
        else:
            decimal_odds = 1 + 100 / abs(odds)

        # EV = (prob * win) - ((1-prob) * loss)
        # For $1 bet: EV = (prob * (decimal_odds - 1)) - (1 - prob)
        ev = (est_prob * (decimal_odds - 1)) - (1 - est_prob)

        return ev

    def analyze_props(self, props: List[PropContext]) -> List[EdgeResult]:
        """
        Analyze multiple props and return sorted by edge strength.

        Args:
            props: List of PropContext objects

        Returns:
            List of EdgeResult, sorted by absolute edge (descending)
        """
        results = []
        for ctx in props:
            try:
                result = self.calculate_edge(ctx)
                results.append(result)
            except Exception as e:
                logger.error(f"Error analyzing prop for {ctx.player_name}: {e}")

        # Sort by absolute edge score (strongest first)
        results.sort(key=lambda x: abs(x.edge_score), reverse=True)

        return results

    def get_top_plays(
        self,
        props: List[PropContext],
        min_edge: float = None,
        max_results: int = 10
    ) -> List[EdgeResult]:
        """
        Get top plays from a list of props.

        Args:
            props: List of props to analyze
            min_edge: Minimum edge threshold (default: MIN_EDGE)
            max_results: Maximum number of results

        Returns:
            Top plays sorted by edge strength
        """
        if min_edge is None:
            min_edge = self.MIN_EDGE

        results = self.analyze_props(props)

        # Filter by edge and recommendation
        filtered = [
            r for r in results
            if abs(r.edge_score) >= min_edge and r.recommendation != 'pass'
        ]

        return filtered[:max_results]


# =============================================================================
# CONVENIENCE
# =============================================================================

_calculator: Optional[EdgeCalculator] = None


def get_edge_calculator() -> EdgeCalculator:
    """Get singleton edge calculator instance."""
    global _calculator
    if _calculator is None:
        _calculator = EdgeCalculator()
    return _calculator
