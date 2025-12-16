"""
Correlation Signal (Weight: 5%)

Analyzes correlation between player props and game totals.
High-scoring games = more individual stats.
"""

from .base import BaseSignal, SignalResult, PropContext


class CorrelationSignal(BaseSignal):
    """
    Evaluates game total impact on individual props.

    NBA context:
    - High totals (230+) suggest fast pace, weak defenses
    - Low totals (210-) suggest slow, defensive games
    - Individual stats correlate with game pace/scoring

    This is a supporting signal that amplifies other signals
    when game conditions align.
    """

    weight = 0.05
    name = "correlation"

    # Game total thresholds (NBA typically 215-235)
    LEAGUE_AVG_TOTAL = 223.0
    HIGH_TOTAL = 230.0
    VERY_HIGH_TOTAL = 238.0
    LOW_TOTAL = 215.0
    VERY_LOW_TOTAL = 208.0

    # Stat correlation with game total
    STAT_TOTAL_CORRELATION = {
        'points': 0.9,      # Highly correlated
        'threes': 0.8,      # High scoring = more 3s
        'assists': 0.7,     # More scoring = more assists
        'rebounds': 0.5,    # Moderate correlation
        'turnovers': 0.4,   # Faster pace = more turnovers
        'steals': 0.4,
        'blocks': 0.3,      # Less affected
        'pra': 0.8,
        'pr': 0.7,
        'pa': 0.8,
        'ra': 0.6,
        'fgm': 0.85,
        'ftm': 0.6,
    }

    def calculate(self, ctx: PropContext) -> SignalResult:
        """
        Calculate correlation signal.

        Positive strength = high total (favor OVER)
        Negative strength = low total (favor UNDER)
        """
        if ctx.game_total is None or ctx.game_total <= 0:
            return SignalResult(
                signal_type=self.name,
                strength=0.0,
                confidence=0.0,
                evidence="No game total available",
                raw_data=None
            )

        total = ctx.game_total

        # Calculate total differential from average
        total_diff = total - self.LEAGUE_AVG_TOTAL

        # Get correlation factor for this stat type
        correlation = self.STAT_TOTAL_CORRELATION.get(ctx.stat_type, 0.5)

        # Calculate base strength
        # +10 points above average → ~0.3 strength (modified by correlation)
        base_strength = (total_diff / 30.0) * correlation

        # Amplify for extreme totals
        if total >= self.VERY_HIGH_TOTAL:
            base_strength *= 1.2
        elif total <= self.VERY_LOW_TOTAL:
            base_strength *= 1.2

        strength = base_strength
        confidence = self._calculate_confidence(ctx, abs(total_diff), correlation)

        # Build evidence
        total_tier = self._get_total_tier(total)

        if strength > 0.02:
            direction = "OVER"
        elif strength < -0.02:
            direction = "UNDER"
        else:
            direction = "neutral"

        evidence = f"Game total {total:.1f} ({total_tier}) → {direction} for {ctx.stat_type}"

        return SignalResult(
            signal_type=self.name,
            strength=self._clamp(strength),
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'game_total': total,
                'total_diff': round(total_diff, 2),
                'stat_correlation': correlation,
                'total_tier': total_tier,
            }
        )

    def _get_total_tier(self, total: float) -> str:
        """Get game total tier description."""
        if total >= self.VERY_HIGH_TOTAL:
            return "very high"
        elif total >= self.HIGH_TOTAL:
            return "high"
        elif total >= self.LEAGUE_AVG_TOTAL:
            return "above average"
        elif total >= self.LOW_TOTAL:
            return "below average"
        elif total >= self.VERY_LOW_TOTAL:
            return "low"
        else:
            return "very low"

    def _calculate_confidence(
        self,
        ctx: PropContext,
        total_diff: float,
        correlation: float
    ) -> float:
        """
        Calculate confidence in correlation signal.
        """
        confidence = 0.4  # Lower base - this is a supporting signal

        # Extreme totals more reliable
        if total_diff >= 10:
            confidence += 0.15
        elif total_diff >= 5:
            confidence += 0.08

        # High correlation stats more reliable
        confidence += correlation * 0.1

        # High value player
        if ctx.is_high_value:
            confidence += 0.05

        return self._clamp(confidence, 0.0, 1.0)
