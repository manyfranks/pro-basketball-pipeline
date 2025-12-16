"""
Line Value Signal (Weight: 30%)

Compares the betting line to statistical projections.
Core edge detection - does the market line disagree with data?
"""

from .base import BaseSignal, SignalResult, PropContext


class LineValueSignal(BaseSignal):
    """
    Detects mispriced lines by comparing to statistical expectations.

    Primary signal - if the line is significantly different from
    what the data suggests, there's potential edge.

    Calculation:
    - Compare line to season average
    - Compare line to recent (L5) average
    - Weight recent performance slightly higher
    - Generate strength based on deviation
    """

    weight = 0.30
    name = "line_value"

    # Thresholds for significant deviation
    MIN_DEVIATION_PCT = 0.05  # 5% deviation minimum to signal
    MAX_DEVIATION_PCT = 0.30  # Cap at 30% deviation

    # Weight for blending season vs recent
    RECENT_WEIGHT = 0.6
    SEASON_WEIGHT = 0.4

    def calculate(self, ctx: PropContext) -> SignalResult:
        """
        Calculate line value signal.

        Positive strength = OVER (line is too low)
        Negative strength = UNDER (line is too high)
        """
        # Blend season and recent averages
        if ctx.recent_avg > 0 and ctx.season_avg > 0:
            expected = (
                ctx.recent_avg * self.RECENT_WEIGHT +
                ctx.season_avg * self.SEASON_WEIGHT
            )
        elif ctx.recent_avg > 0:
            expected = ctx.recent_avg
        elif ctx.season_avg > 0:
            expected = ctx.season_avg
        else:
            # No data - return neutral signal
            return SignalResult(
                signal_type=self.name,
                strength=0.0,
                confidence=0.0,
                evidence="Insufficient data for line value analysis",
                raw_data={'expected': None, 'line': ctx.line}
            )

        # Calculate deviation
        if expected == 0:
            return SignalResult(
                signal_type=self.name,
                strength=0.0,
                confidence=0.0,
                evidence="Expected value is zero",
                raw_data={'expected': 0, 'line': ctx.line}
            )

        deviation = (expected - ctx.line) / expected
        deviation_pct = abs(deviation)

        # Determine if deviation is significant
        if deviation_pct < self.MIN_DEVIATION_PCT:
            strength = 0.0
            confidence = 0.2
            evidence = f"Line ({ctx.line}) is close to expected ({expected:.1f})"
        else:
            # Scale strength based on deviation
            # Cap at MAX_DEVIATION_PCT for strength calculation
            capped_deviation = min(deviation_pct, self.MAX_DEVIATION_PCT)

            # Map deviation to strength [-1, 1]
            # At MIN_DEVIATION_PCT = 0, at MAX_DEVIATION_PCT = 1
            strength_magnitude = (capped_deviation - self.MIN_DEVIATION_PCT) / (
                self.MAX_DEVIATION_PCT - self.MIN_DEVIATION_PCT
            )

            # Apply direction (positive deviation = expected > line = OVER)
            strength = strength_magnitude if deviation > 0 else -strength_magnitude

            # Confidence based on data quality
            confidence = self._calculate_confidence(ctx, deviation_pct)

            direction = "OVER" if strength > 0 else "UNDER"
            evidence = (
                f"Line {ctx.line} vs expected {expected:.1f} "
                f"({deviation_pct*100:.1f}% deviation → {direction})"
            )

        return SignalResult(
            signal_type=self.name,
            strength=self._clamp(strength),
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'line': ctx.line,
                'expected': round(expected, 2),
                'season_avg': ctx.season_avg,
                'recent_avg': ctx.recent_avg,
                'deviation_pct': round(deviation_pct * 100, 2),
            }
        )

    def _calculate_confidence(self, ctx: PropContext, deviation_pct: float) -> float:
        """
        Calculate confidence based on:
        - Games played (more games = higher confidence)
        - Is high value player (higher confidence)
        - Deviation magnitude (too extreme = lower confidence)
        """
        confidence = 0.5  # Base confidence

        # Games played factor (max +0.2 at 20+ games)
        games_factor = min(ctx.games_played / 20, 1.0) * 0.2
        confidence += games_factor

        # High value player bonus
        if ctx.is_high_value:
            confidence += 0.1

        # Extreme deviation penalty (>25% deviation suspicious)
        if deviation_pct > 0.25:
            confidence -= 0.15

        # Recent data quality (need recent games)
        if ctx.recent_avg > 0:
            confidence += 0.1

        return self._clamp(confidence, 0.0, 1.0)
