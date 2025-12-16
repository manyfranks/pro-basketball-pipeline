"""
Trend Signal (Weight: 20%)

Analyzes recent performance trends to detect momentum.
Is the player trending up or down from their baseline?
"""

from .base import BaseSignal, SignalResult, PropContext


class TrendSignal(BaseSignal):
    """
    Detects performance trends by comparing recent to season averages.

    NBA context:
    - Hot streaks are real (shooting confidence)
    - Cold streaks can persist (fatigue, injury lingering)
    - Recent 5 games weighted heavily

    Calculation:
    - Compare L5 average to season average
    - Detect trend direction and magnitude
    - Consider minutes trend (playing time changes)
    """

    weight = 0.20
    name = "trend"

    # Thresholds
    MIN_TREND_PCT = 0.10  # 10% change to signal
    MAX_TREND_PCT = 0.40  # Cap at 40%

    def calculate(self, ctx: PropContext) -> SignalResult:
        """
        Calculate trend signal.

        Positive strength = player trending UP (favor OVER)
        Negative strength = player trending DOWN (favor UNDER)
        """
        # Need both averages
        if ctx.season_avg <= 0 or ctx.recent_avg <= 0:
            return SignalResult(
                signal_type=self.name,
                strength=0.0,
                confidence=0.0,
                evidence="Insufficient data for trend analysis",
                raw_data=None
            )

        # Calculate trend percentage
        trend_pct = (ctx.recent_avg - ctx.season_avg) / ctx.season_avg
        abs_trend = abs(trend_pct)

        # Minutes trend (if available)
        minutes_trend = 0.0
        if ctx.minutes_per_game > 0 and ctx.recent_minutes > 0:
            minutes_trend = (ctx.recent_minutes - ctx.minutes_per_game) / ctx.minutes_per_game

        # Determine significance
        if abs_trend < self.MIN_TREND_PCT:
            strength = 0.0
            confidence = 0.2
            evidence = f"Stable performance (L5: {ctx.recent_avg:.1f} vs Season: {ctx.season_avg:.1f})"
        else:
            # Scale trend to strength
            capped_trend = min(abs_trend, self.MAX_TREND_PCT)
            strength_magnitude = (capped_trend - self.MIN_TREND_PCT) / (
                self.MAX_TREND_PCT - self.MIN_TREND_PCT
            )

            # Apply direction
            strength = strength_magnitude if trend_pct > 0 else -strength_magnitude

            # Boost/reduce based on minutes trend
            # If minutes trending same direction as stats, boost confidence
            if minutes_trend * trend_pct > 0:
                # Same direction - trend is supported by playing time
                strength *= 1.1
            elif abs(minutes_trend) > 0.1 and minutes_trend * trend_pct < 0:
                # Opposite direction - stat trend despite minutes change
                # Could mean efficiency change - moderate the signal
                strength *= 0.85

            confidence = self._calculate_confidence(ctx, abs_trend, minutes_trend)

            direction = "UP" if strength > 0 else "DOWN"
            evidence = (
                f"Trending {direction}: L5 avg {ctx.recent_avg:.1f} vs "
                f"season {ctx.season_avg:.1f} ({trend_pct*100:+.1f}%)"
            )
            if abs(minutes_trend) > 0.05:
                min_dir = "+" if minutes_trend > 0 else ""
                evidence += f" [Minutes: {min_dir}{minutes_trend*100:.0f}%]"

        return SignalResult(
            signal_type=self.name,
            strength=self._clamp(strength),
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'season_avg': ctx.season_avg,
                'recent_avg': ctx.recent_avg,
                'trend_pct': round(trend_pct * 100, 2),
                'minutes_trend_pct': round(minutes_trend * 100, 2),
            }
        )

    def _calculate_confidence(
        self,
        ctx: PropContext,
        trend_magnitude: float,
        minutes_trend: float
    ) -> float:
        """
        Calculate confidence based on:
        - Sample size (games played)
        - Trend sustainability (extreme trends less confident)
        - Minutes stability
        """
        confidence = 0.5

        # Games played factor
        games_factor = min(ctx.games_played / 20, 1.0) * 0.15
        confidence += games_factor

        # Extreme trend penalty (>30% change less reliable)
        if trend_magnitude > 0.30:
            confidence -= 0.15

        # Minutes stability bonus
        if abs(minutes_trend) < 0.05:
            confidence += 0.1  # Stable minutes = more reliable trend

        # High value player bonus
        if ctx.is_high_value:
            confidence += 0.1

        return self._clamp(confidence, 0.0, 1.0)
