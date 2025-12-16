"""
Usage Signal (Weight: 20%)

Analyzes player's usage rate and role in offense.
High usage + good opportunity = potential edge.
"""

from .base import BaseSignal, SignalResult, PropContext


class UsageSignal(BaseSignal):
    """
    Evaluates player's offensive role and opportunity.

    NBA context:
    - Usage rate (USG%) = % of team plays used while on court
    - High usage players are more predictable
    - Minutes matter - more time = more opportunity

    Key insight: High usage players with consistent minutes
    are the most predictable for props.
    """

    weight = 0.20
    name = "usage"

    # Usage thresholds (league avg ~20%)
    HIGH_USAGE = 25.0      # Star-level usage
    ELITE_USAGE = 30.0     # Superstar usage
    LOW_USAGE = 15.0       # Role player

    # Minutes thresholds
    STARTER_MINUTES = 28.0
    HIGH_MINUTES = 32.0

    def calculate(self, ctx: PropContext) -> SignalResult:
        """
        Calculate usage signal.

        This signal is about opportunity and predictability:
        - High usage + high minutes = good OVER candidate
        - Low usage OR low minutes = uncertainty
        """
        if ctx.usage_pct <= 0 or ctx.minutes_per_game <= 0:
            return SignalResult(
                signal_type=self.name,
                strength=0.0,
                confidence=0.0,
                evidence="Insufficient usage/minutes data",
                raw_data=None
            )

        # Calculate usage score
        usage_score = self._calculate_usage_score(ctx.usage_pct)

        # Calculate minutes score
        minutes_score = self._calculate_minutes_score(ctx.minutes_per_game)

        # Combined opportunity score
        # High usage AND high minutes = strong signal
        opportunity_score = (usage_score * 0.6 + minutes_score * 0.4)

        # Compare line to what usage/minutes suggest
        # This is subtle - we're not directly predicting over/under
        # We're assessing if this player is a good candidate for props
        strength = self._evaluate_line_vs_opportunity(ctx, opportunity_score)

        confidence = self._calculate_confidence(ctx, usage_score, minutes_score)

        # Build evidence
        usage_tier = self._get_usage_tier(ctx.usage_pct)
        minutes_tier = self._get_minutes_tier(ctx.minutes_per_game)

        if strength > 0:
            direction = "Favorable OVER"
        elif strength < 0:
            direction = "Favorable UNDER"
        else:
            direction = "Neutral"

        evidence = (
            f"{usage_tier} usage ({ctx.usage_pct:.1f}%), "
            f"{minutes_tier} minutes ({ctx.minutes_per_game:.1f}) → {direction}"
        )

        return SignalResult(
            signal_type=self.name,
            strength=self._clamp(strength),
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'usage_pct': ctx.usage_pct,
                'minutes_per_game': ctx.minutes_per_game,
                'usage_score': round(usage_score, 3),
                'minutes_score': round(minutes_score, 3),
                'opportunity_score': round(opportunity_score, 3),
            }
        )

    def _calculate_usage_score(self, usage_pct: float) -> float:
        """Score usage rate (0.0 to 1.0)."""
        if usage_pct >= self.ELITE_USAGE:
            return 1.0
        elif usage_pct >= self.HIGH_USAGE:
            return 0.6 + (usage_pct - self.HIGH_USAGE) / (self.ELITE_USAGE - self.HIGH_USAGE) * 0.4
        elif usage_pct >= self.LOW_USAGE:
            return (usage_pct - self.LOW_USAGE) / (self.HIGH_USAGE - self.LOW_USAGE) * 0.6
        else:
            return max(0, usage_pct / self.LOW_USAGE * 0.2)

    def _calculate_minutes_score(self, minutes: float) -> float:
        """Score minutes per game (0.0 to 1.0)."""
        if minutes >= self.HIGH_MINUTES:
            return 1.0
        elif minutes >= self.STARTER_MINUTES:
            return 0.6 + (minutes - self.STARTER_MINUTES) / (self.HIGH_MINUTES - self.STARTER_MINUTES) * 0.4
        else:
            return max(0, minutes / self.STARTER_MINUTES * 0.6)

    def _evaluate_line_vs_opportunity(self, ctx: PropContext, opportunity_score: float) -> float:
        """
        Evaluate if the line reflects the player's opportunity.

        High opportunity players with lines below recent average = OVER
        Low opportunity players with lines above recent average = UNDER
        """
        if ctx.recent_avg <= 0 or ctx.line <= 0:
            return 0.0

        # Line relative to recent performance
        line_vs_recent = (ctx.recent_avg - ctx.line) / ctx.recent_avg

        # High opportunity amplifies the signal
        if opportunity_score >= 0.7:
            # Star player - if line is low, lean over
            if line_vs_recent > 0.05:
                return opportunity_score * 0.5  # Moderate over lean
            elif line_vs_recent < -0.10:
                # Line is high for even a star - caution
                return -0.2
        elif opportunity_score < 0.4:
            # Low opportunity player
            if line_vs_recent > 0.10:
                # Line seems low but player has low opportunity
                return 0.1  # Slight over but uncertain
            elif line_vs_recent < -0.05:
                return -opportunity_score * 0.3  # Lean under

        # Middle ground - small signal
        return line_vs_recent * 0.3

    def _get_usage_tier(self, usage_pct: float) -> str:
        """Get usage tier label."""
        if usage_pct >= self.ELITE_USAGE:
            return "Elite"
        elif usage_pct >= self.HIGH_USAGE:
            return "High"
        elif usage_pct >= 20:
            return "Average"
        else:
            return "Low"

    def _get_minutes_tier(self, minutes: float) -> str:
        """Get minutes tier label."""
        if minutes >= self.HIGH_MINUTES:
            return "high"
        elif minutes >= self.STARTER_MINUTES:
            return "starter"
        else:
            return "limited"

    def _calculate_confidence(
        self,
        ctx: PropContext,
        usage_score: float,
        minutes_score: float
    ) -> float:
        """Calculate confidence based on usage stability and sample size."""
        confidence = 0.4

        # High usage = more predictable
        confidence += usage_score * 0.2

        # High minutes = more opportunity
        confidence += minutes_score * 0.15

        # Games played
        if ctx.games_played >= 20:
            confidence += 0.15
        elif ctx.games_played >= 10:
            confidence += 0.08

        # High value bonus
        if ctx.is_high_value:
            confidence += 0.1

        return self._clamp(confidence, 0.0, 1.0)
