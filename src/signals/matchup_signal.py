"""
Matchup Signal (Weight: 15%)

Analyzes opponent defensive quality and matchup.
NOW WITH STAT-SPECIFIC LOGIC:
- Points/Threes: Uses DEF_RTG (defensive rating)
- Rebounds: Uses OREB%/DREB% (rebounding rates) - FIXED!
- Assists: Uses DEF_RTG + pace correlation
"""

from .base import BaseSignal, SignalResult, PropContext


class MatchupSignal(BaseSignal):
    """
    Evaluates opponent defense impact on player props.

    STAT-SPECIFIC LOGIC (key insight from backtest):
    - Points/Threes: DEF_RTG is highly predictive
    - Rebounds: DEF_RTG is USELESS (47% hit rate), need OREB%/DREB%
    - Assists: DEF_RTG + pace matters

    League averages (2024-25):
    - DEF_RTG: ~112-114
    - OREB%: ~25%
    - DREB%: ~75%
    """

    weight = 0.15
    name = "matchup"

    # Defensive rating thresholds (for points/threes/assists)
    LEAGUE_AVG_DEF_RTG = 112.0
    BAD_DEFENSE = 116.0
    AWFUL_DEFENSE = 119.0
    GOOD_DEFENSE = 109.0
    ELITE_DEFENSE = 106.0

    # Rebounding thresholds (league averages)
    LEAGUE_AVG_OREB_PCT = 0.25  # 25% of available offensive rebounds
    LEAGUE_AVG_DREB_PCT = 0.75  # 75% of available defensive rebounds

    # Rebounding tier thresholds
    BAD_DREB_PCT = 0.72     # Bottom 10 - gives up more OREBs
    AWFUL_DREB_PCT = 0.70   # Bottom 5
    GOOD_DREB_PCT = 0.77    # Top 10
    ELITE_DREB_PCT = 0.79   # Top 5

    def calculate(self, ctx: PropContext) -> SignalResult:
        """
        Calculate matchup signal with STAT-SPECIFIC LOGIC.
        """
        # Route to stat-specific calculations
        if ctx.stat_type == 'rebounds':
            return self._calculate_rebounds_matchup(ctx)
        elif ctx.stat_type == 'assists':
            return self._calculate_assists_matchup(ctx)
        else:
            return self._calculate_scoring_matchup(ctx)

    def _calculate_rebounds_matchup(self, ctx: PropContext) -> SignalResult:
        """
        Calculate matchup signal for REBOUNDS using rebounding rates.

        Key insight: DEF_RTG is useless for rebounds (47% hit rate).
        Instead use:
        - Opponent DREB%: Low DREB% = more OREB chances for us
        - Opponent OREB%: High OREB% = they crash boards, fewer DREB chances
        - Player's contested vs uncontested rebound profile
        """
        opp_dreb_pct = ctx.opponent_dreb_pct
        opp_oreb_pct = ctx.opponent_oreb_pct

        # Check if we have rebounding data
        if opp_dreb_pct <= 0 and opp_oreb_pct <= 0:
            return SignalResult(
                signal_type=self.name,
                strength=0.0,
                confidence=0.0,
                evidence="No opponent rebounding data",
                raw_data=None
            )

        # Use fallback if missing
        if opp_dreb_pct <= 0:
            opp_dreb_pct = self.LEAGUE_AVG_DREB_PCT
        if opp_oreb_pct <= 0:
            opp_oreb_pct = self.LEAGUE_AVG_OREB_PCT

        # Calculate rebounding differential
        # Low opponent DREB% = more rebounds available for us (good for OVER)
        # High opponent OREB% = they crash boards, fewer DREBs for us (bad for OVER)
        dreb_diff = self.LEAGUE_AVG_DREB_PCT - opp_dreb_pct  # Positive = good for us
        oreb_diff = opp_oreb_pct - self.LEAGUE_AVG_OREB_PCT  # Positive = bad for us

        # Net rebounding opportunity
        # If opponent has bad DREB%, we get more boards
        # Weight DREB more heavily since most rebounds are defensive
        net_reb_diff = (dreb_diff * 0.7) - (oreb_diff * 0.3)

        # Scale to strength
        # 5% DREB differential is significant
        base_strength = (net_reb_diff / 0.08)

        # Adjust for player's rebound profile
        # High contested rebound % = more skill-dependent, less matchup-dependent
        if ctx.contested_reb_pct > 0.5:
            base_strength *= 0.7  # Reduce matchup impact for contested rebounders
        elif ctx.uncontested_reb_pct > 0.6:
            base_strength *= 1.2  # Amplify for uncontested rebounders (more opportunity-based)

        # Adjust for pace
        pace_adj = self._pace_adjustment(ctx.opponent_pace)
        strength = base_strength + (pace_adj * 0.5)  # Pace matters less for rebounds

        # Build evidence
        reb_tier = self._get_rebounding_tier(opp_dreb_pct)
        confidence = self._calculate_rebounds_confidence(ctx, abs(net_reb_diff))

        if strength > 0.05:
            direction = "OVER"
        elif strength < -0.05:
            direction = "UNDER"
        else:
            direction = "neutral"

        evidence = (
            f"vs {ctx.opponent_team} ({reb_tier} rebounding, "
            f"DREB%: {opp_dreb_pct:.1%}) → {direction}"
        )

        return SignalResult(
            signal_type=self.name,
            strength=self._clamp(strength),
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'opponent': ctx.opponent_team,
                'opp_dreb_pct': opp_dreb_pct,
                'opp_oreb_pct': opp_oreb_pct,
                'net_reb_diff': round(net_reb_diff, 4),
                'player_contested_pct': ctx.contested_reb_pct,
            }
        )

    def _calculate_assists_matchup(self, ctx: PropContext) -> SignalResult:
        """
        Calculate matchup signal for ASSISTS.

        Uses DEF_RTG but with emphasis on pace and ball movement.
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

        # Calculate defensive differential
        def_diff = opp_def_rtg - self.LEAGUE_AVG_DEF_RTG

        # Assists are moderately affected by defense
        base_strength = (def_diff / 12.0) * 0.6

        # Pace is MORE important for assists (more possessions = more opportunities)
        pace_adj = self._pace_adjustment(ctx.opponent_pace)
        strength = base_strength + (pace_adj * 1.5)  # Amplify pace for assists

        # Adjust for player's pass profile
        if ctx.pass_to_ast_rate > 0.1:  # High assist conversion
            strength *= 1.1

        def_tier = self._get_defense_tier(opp_def_rtg)
        confidence = self._calculate_confidence(ctx, abs(def_diff), 0.7)

        if strength > 0.05:
            direction = "OVER"
        elif strength < -0.05:
            direction = "UNDER"
        else:
            direction = "neutral"

        evidence = (
            f"vs {ctx.opponent_team} ({def_tier} defense, pace: {ctx.opponent_pace:.1f}) → {direction}"
        )

        return SignalResult(
            signal_type=self.name,
            strength=self._clamp(strength),
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'opponent': ctx.opponent_team,
                'opp_def_rtg': opp_def_rtg,
                'opp_pace': ctx.opponent_pace,
                'def_diff': round(def_diff, 2),
            }
        )

    def _calculate_scoring_matchup(self, ctx: PropContext) -> SignalResult:
        """
        Calculate matchup signal for POINTS/THREES/other scoring stats.

        Uses DEF_RTG - the traditional approach that works well for scoring.
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

        # Calculate defensive differential
        def_diff = opp_def_rtg - self.LEAGUE_AVG_DEF_RTG

        # Impact multiplier by stat type
        impact_map = {
            'points': 1.0,
            'threes': 0.9,
            'fgm': 0.9,
            'ftm': 0.7,
            'pra': 0.85,
            'pr': 0.75,
            'pa': 0.85,
        }
        impact_mult = impact_map.get(ctx.stat_type, 0.8)

        # Calculate base strength
        base_strength = (def_diff / 12.0) * impact_mult

        # Pace adjustment
        pace_adj = self._pace_adjustment(ctx.opponent_pace)
        strength = base_strength + pace_adj

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
        if abs(pace_adj) > 0.02:
            pace_desc = "fast" if pace_adj > 0 else "slow"
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
        """Adjust signal for opponent pace."""
        if pace <= 0:
            return 0.0

        league_avg_pace = 99.5
        pace_diff = pace - league_avg_pace
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

    def _get_rebounding_tier(self, dreb_pct: float) -> str:
        """Get rebounding quality tier based on DREB%."""
        if dreb_pct <= self.AWFUL_DREB_PCT:
            return "awful"
        elif dreb_pct <= self.BAD_DREB_PCT:
            return "weak"
        elif dreb_pct <= self.LEAGUE_AVG_DREB_PCT:
            return "average"
        elif dreb_pct <= self.GOOD_DREB_PCT:
            return "good"
        else:
            return "elite"

    def _calculate_confidence(
        self,
        ctx: PropContext,
        def_diff: float,
        impact_mult: float
    ) -> float:
        """Calculate confidence for scoring matchups."""
        confidence = 0.5

        if def_diff >= 5:
            confidence += 0.15
        elif def_diff >= 3:
            confidence += 0.08

        confidence += impact_mult * 0.1

        if ctx.is_high_value:
            confidence += 0.1

        if ctx.opponent_team:
            confidence += 0.05

        return self._clamp(confidence, 0.0, 1.0)

    def _calculate_rebounds_confidence(
        self,
        ctx: PropContext,
        net_reb_diff: float
    ) -> float:
        """Calculate confidence for rebounds matchups."""
        confidence = 0.5

        # Extreme rebounding matchups are more reliable
        if net_reb_diff >= 0.05:
            confidence += 0.15
        elif net_reb_diff >= 0.03:
            confidence += 0.08

        # Have player rebound tracking data = higher confidence
        if ctx.reb_frequency > 0:
            confidence += 0.1

        if ctx.is_high_value:
            confidence += 0.1

        if ctx.opponent_team:
            confidence += 0.05

        return self._clamp(confidence, 0.0, 1.0)
