"""
Matchup Signal (Weight: 15%)

Analyzes opponent defensive quality and matchup.
Weak defense = potential OVER opportunity.
"""

from .base import BaseSignal, SignalResult, PropContext


class MatchupSignal(BaseSignal):
    """
    Evaluates opponent defense impact on player props.

    NBA context:
    - Defensive rating (DEF_RTG) = points allowed per 100 possessions
    - League average ~112-114
    - Bad defenses (118+) inflate scoring
    - Elite defenses (108-) suppress stats

    Stat-specific considerations:
    - Points: Direct correlation with DEF_RTG
    - Rebounds: Team rebounding rate matters
    - Assists: Ball movement vs tight D
    """

    weight = 0.15
    name = "matchup"

    # Defensive rating thresholds (2024-25 calibrated)
    LEAGUE_AVG_DEF_RTG = 112.0
    BAD_DEFENSE = 116.0      # Bottom 10 defenses
    AWFUL_DEFENSE = 119.0    # Bottom 5
    GOOD_DEFENSE = 109.0     # Top 10
    ELITE_DEFENSE = 106.0    # Top 5

    # Stat type defensive impact multipliers
    # How much does defense affect this stat type?
    STAT_DEFENSE_IMPACT = {
        'points': 1.0,      # Most affected
        'threes': 0.9,      # Highly affected by perimeter D
        'assists': 0.7,     # Somewhat affected
        'rebounds': 0.5,    # Less affected by DEF_RTG
        'steals': 0.4,      # More about player skill
        'blocks': 0.4,      # More about player skill
        'turnovers': 0.6,   # Affected by defensive pressure
        'pra': 0.85,        # Combo - average impact
        'pr': 0.75,
        'pa': 0.85,
        'ra': 0.6,
        'fgm': 0.9,
        'ftm': 0.7,
    }

    def calculate(self, ctx: PropContext) -> SignalResult:
        """
        Calculate matchup signal.

        Positive strength = favorable matchup (OVER)
        Negative strength = tough matchup (UNDER)
        """
        opp_def_rtg = ctx.opponent_def_rating

        if opp_def_rtg <= 0:
            return SignalResult(
                signal_type=self.name,
                strength=0.0,
                confidence=0.0,
                evidence="No opponent defensive data",
                raw_data=None
            )

        # Calculate defensive differential from league average
        def_diff = opp_def_rtg - self.LEAGUE_AVG_DEF_RTG

        # Get stat-specific impact multiplier
        impact_mult = self.STAT_DEFENSE_IMPACT.get(ctx.stat_type, 0.7)

        # Calculate base strength from defensive differential
        # +6 DEF_RTG (awful defense) → ~0.5 strength
        # -6 DEF_RTG (elite defense) → ~-0.5 strength
        base_strength = (def_diff / 12.0) * impact_mult

        # Adjust for opponent pace (faster pace = more possessions = more stats)
        pace_adjustment = self._pace_adjustment(ctx.opponent_pace)
        strength = base_strength + pace_adjustment

        # Build evidence
        def_tier = self._get_defense_tier(opp_def_rtg)
        confidence = self._calculate_confidence(ctx, abs(def_diff), impact_mult)

        if strength > 0.05:
            direction = "OVER"
        elif strength < -0.05:
            direction = "UNDER"
        else:
            direction = "neutral"

        evidence = (
            f"vs {ctx.opponent_team} ({def_tier} defense, {opp_def_rtg:.1f} DEF_RTG) → {direction}"
        )
        if abs(pace_adjustment) > 0.02:
            pace_desc = "fast" if pace_adjustment > 0 else "slow"
            evidence += f" [{pace_desc} pace]"

        return SignalResult(
            signal_type=self.name,
            strength=self._clamp(strength),
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'opponent': ctx.opponent_team,
                'opp_def_rtg': opp_def_rtg,
                'def_diff': round(def_diff, 2),
                'opp_pace': ctx.opponent_pace,
                'stat_impact': impact_mult,
            }
        )

    def _pace_adjustment(self, pace: float) -> float:
        """
        Adjust signal for opponent pace.
        League avg pace ~99-100.
        """
        if pace <= 0:
            return 0.0

        league_avg_pace = 99.5
        pace_diff = pace - league_avg_pace

        # +3 pace → +0.05 strength adjustment
        return pace_diff / 60.0

    def _get_defense_tier(self, def_rtg: float) -> str:
        """Get defense quality tier."""
        if def_rtg >= self.AWFUL_DEFENSE:
            return "awful"
        elif def_rtg >= self.BAD_DEFENSE:
            return "weak"
        elif def_rtg >= self.LEAGUE_AVG_DEF_RTG:
            return "average"
        elif def_rtg >= self.GOOD_DEFENSE:
            return "good"
        elif def_rtg >= self.ELITE_DEFENSE:
            return "strong"
        else:
            return "elite"

    def _calculate_confidence(
        self,
        ctx: PropContext,
        def_diff: float,
        impact_mult: float
    ) -> float:
        """
        Calculate confidence based on:
        - How extreme the defensive matchup is
        - Stat type relevance to defense
        - Player's high value status
        """
        confidence = 0.5

        # Extreme matchups are more reliable
        if def_diff >= 5:
            confidence += 0.15
        elif def_diff >= 3:
            confidence += 0.08

        # High impact stat types more reliable
        confidence += impact_mult * 0.1

        # High value player bonus
        if ctx.is_high_value:
            confidence += 0.1

        # Have opponent data
        if ctx.opponent_team:
            confidence += 0.05

        return self._clamp(confidence, 0.0, 1.0)
