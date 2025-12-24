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

    NOW WITH STAT-SPECIFIC WEIGHTS based on backtest analysis:

    POINTS (all signals work 66-72%):
    - environment: 15% (72% hit rate - best signal!)
    - correlation: 20%, usage: 15%, trend: 20%, line_value: 15%, matchup: 15%

    REBOUNDS (only Environment works, matchup/usage are anti-predictive):
    - environment: 40% (80% on overs!)
    - line_value: 25%, trend: 20%, correlation: 15%
    - matchup: 0%, usage: 0% (47% - worse than coin flip)

    ASSISTS (all signals moderate 59-64%):
    - matchup: 20% (64%), line_value: 20%, trend: 15%, usage: 15%
    - correlation: 15%, environment: 15%

    Philosophy:
    - Trust market lines as baseline
    - Use stat-specific signal weights
    - Weight signals by their actual predictive value per stat type
    """

    # STAT-SPECIFIC SIGNAL WEIGHTS (must sum to 1.0)
    # Based on backtest hit rates per stat type
    STAT_WEIGHTS = {
        'points': {
            'environment': 0.15,   # 72% hit rate - boost!
            'correlation': 0.20,   # 69%
            'usage': 0.15,         # 69%
            'trend': 0.20,         # 67%
            'line_value': 0.15,    # 66%
            'matchup': 0.15,       # 66%
        },
        'rebounds': {
            'environment': 0.40,   # 66%/80% on overs - only reliable signal!
            'line_value': 0.25,    # 51%
            'trend': 0.20,         # 51%
            'correlation': 0.15,   # 50%
            'matchup': 0.00,       # 47% - anti-predictive, zero out
            'usage': 0.00,         # 47% - anti-predictive, zero out
        },
        'assists': {
            'matchup': 0.20,       # 64%
            'line_value': 0.20,    # 62%
            'trend': 0.15,         # 61%
            'usage': 0.15,         # 61%
            'correlation': 0.15,   # 61%
            'environment': 0.15,   # 59%
        },
        'threes': {
            # Limited data - use balanced weights
            'line_value': 0.25,
            'trend': 0.20,
            'correlation': 0.20,
            'matchup': 0.15,
            'environment': 0.10,
            'usage': 0.10,
        },
        # Default weights for other stat types
        '_default': {
            'line_value': 0.25,
            'trend': 0.20,
            'correlation': 0.20,
            'matchup': 0.15,
            'usage': 0.10,
            'environment': 0.10,
        }
    }

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

        # Create lookup by signal name
        self.signal_by_name = {s.name: s for s in self.signals}

    def _get_weights_for_stat(self, stat_type: str) -> Dict[str, float]:
        """Get signal weights for a specific stat type."""
        if stat_type in self.STAT_WEIGHTS:
            return self.STAT_WEIGHTS[stat_type]
        return self.STAT_WEIGHTS['_default']

    def calculate_edge(self, ctx: PropContext) -> EdgeResult:
        """
        Calculate edge for a player prop using STAT-SPECIFIC WEIGHTS.

        Args:
            ctx: Full prop context

        Returns:
            EdgeResult with edge score, direction, and recommendation
        """
        # Get stat-specific weights
        weights = self._get_weights_for_stat(ctx.stat_type)

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

        # Calculate weighted edge score using STAT-SPECIFIC weights
        total_weighted_strength = 0.0
        total_weighted_confidence = 0.0
        total_weight = 0.0

        for signal, result in zip(self.signals, signal_results):
            # Use stat-specific weight instead of signal's default weight
            weight = weights.get(signal.name, 0.0)

            if weight > 0:  # Only include signals with non-zero weight
                weighted_strength = result.strength * weight
                weighted_confidence = result.confidence * weight

                total_weighted_strength += weighted_strength
                total_weighted_confidence += weighted_confidence
                total_weight += weight

        # Normalize
        if total_weight > 0:
            edge_score = total_weighted_strength  # Already weighted
            confidence = total_weighted_confidence / total_weight
        else:
            edge_score = 0.0
            confidence = 0.0

        # Determine direction
        direction = 'over' if edge_score > 0 else 'under'

        # Calculate recommendation (pass signals for stat-specific filtering)
        recommendation = self._get_recommendation(edge_score, confidence, ctx, signal_results)

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
        ctx: PropContext,
        signal_results: List[SignalResult] = None
    ) -> str:
        """
        Generate recommendation based on edge, confidence, and STAT-SPECIFIC RULES.

        CRITICAL INSIGHT from backtest:
        - Rebounds OVERS with favorable environment: 80% hit rate!
        - Rebounds UNDERS: Only 59% even with environment
        - Assists need matchup signal alignment

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

        # =================================================================
        # STAT-SPECIFIC FILTERING (based on backtest data)
        # =================================================================

        # REBOUNDS: CRITICAL FILTERING based on backtest data
        # - Overs with positive env: 76.5% hit rate
        # - Overs with neutral env: 31.4% hit rate (TERRIBLE!)
        # - Only take rebounds when env aligns with direction
        if ctx.stat_type == 'rebounds':
            env_signal = self._get_signal_strength(signal_results, 'environment')

            # If no environment signal, PASS (neutral env = 31% on overs!)
            if env_signal is None or abs(env_signal) < 0.05:
                return 'pass'

            env_suggests_over = env_signal > 0

            if direction == 'over':
                # OVERS: Require positive environment (76.5% hit rate)
                if not env_suggests_over:
                    return 'pass'  # Environment suggests under, don't bet over
                # Environment aligns - this is our best scenario!
                if abs_edge >= self.MIN_EDGE and confidence >= 0.40:
                    if abs_edge >= self.MODERATE_EDGE:
                        return 'strong_over'  # High confidence pick
                    return 'lean_over'

            else:  # direction == 'under'
                # UNDERS: Require negative environment (55% hit rate)
                if env_suggests_over:
                    return 'pass'  # Environment suggests over, don't bet under
                # Environment aligns with under
                if abs_edge >= self.MODERATE_EDGE and confidence >= 0.50:
                    return f'lean_under'

        # ASSISTS: Require higher edge threshold (61.8% base rate, need to be selective)
        # Not enough data to implement signal-based filtering (only 11 legs for key finding)
        # Just raise the bar until we have more forward data
        elif ctx.stat_type == 'assists':
            if abs_edge < self.MODERATE_EDGE:  # Require 0.15 instead of 0.08
                return 'pass'

        # =================================================================
        # STANDARD RECOMMENDATION LOGIC
        # =================================================================

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

    def _get_signal_strength(
        self,
        signal_results: List[SignalResult],
        signal_name: str
    ) -> Optional[float]:
        """Get strength of a specific signal from results."""
        if not signal_results:
            return None
        for s in signal_results:
            if s.signal_type == signal_name:
                return s.strength
        return None

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
