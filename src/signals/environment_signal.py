"""
Environment Signal (Weight: 10%)

Analyzes situational factors: B2B, home/away, rest days, travel.
Context that affects performance beyond matchup.
"""

from .base import BaseSignal, SignalResult, PropContext


class EnvironmentSignal(BaseSignal):
    """
    Evaluates environmental/situational factors.

    NBA context:
    - Back-to-backs significantly impact performance
    - 3 games in 4 nights even worse
    - Home court advantage exists but modest
    - Schedule spots matter (trap games, etc.)

    B2B Impact (research-backed):
    - Points: -2 to -4 points on average
    - Rebounds: -0.5 to -1
    - Assists: -0.5 to -1
    - Most stars rest or have reduced minutes
    """

    weight = 0.10
    name = "environment"

    # B2B impact factors by stat type (negative = reduces stat)
    B2B_IMPACT = {
        'points': -0.25,     # Significant reduction
        'rebounds': -0.15,
        'assists': -0.15,
        'threes': -0.20,     # Shooting affected by fatigue
        'blocks': -0.10,
        'steals': -0.10,
        'turnovers': 0.10,   # Fatigue increases turnovers
        'pra': -0.20,
        'pr': -0.20,
        'pa': -0.20,
        'ra': -0.15,
        'fgm': -0.20,
        'ftm': -0.15,
    }

    # 3-in-4 is worse than B2B
    THREE_IN_FOUR_MULTIPLIER = 1.5

    # Home court advantage (modest)
    HOME_ADVANTAGE = 0.05

    def calculate(self, ctx: PropContext) -> SignalResult:
        """
        Calculate environment signal.

        Negative strength = unfavorable conditions (UNDER)
        Positive strength = favorable conditions (OVER)
        """
        factors = []
        total_impact = 0.0

        # Back-to-back impact
        if ctx.is_b2b:
            b2b_impact = self.B2B_IMPACT.get(ctx.stat_type, -0.15)

            # 3-in-4 is worse
            if ctx.is_3_in_4:
                b2b_impact *= self.THREE_IN_FOUR_MULTIPLIER
                factors.append(f"3-in-4 nights ({b2b_impact*100:.0f}% impact)")
            else:
                factors.append(f"B2B ({b2b_impact*100:.0f}% impact)")

            total_impact += b2b_impact

        # Home/away
        if ctx.is_home:
            total_impact += self.HOME_ADVANTAGE
            factors.append("Home court (+5%)")
        else:
            factors.append("Road game")

        # Blowout risk (from spread)
        if ctx.spread is not None:
            blowout_impact = self._blowout_risk(ctx.spread, ctx.is_home)
            if abs(blowout_impact) > 0.03:
                total_impact += blowout_impact
                direction = "reduced" if blowout_impact < 0 else "extended"
                factors.append(f"Blowout risk ({direction} minutes)")

        # Build strength and evidence
        strength = total_impact

        if abs(strength) < 0.03:
            strength = 0.0
            confidence = 0.3
        else:
            confidence = self._calculate_confidence(ctx)

        if strength > 0:
            direction = "OVER"
        elif strength < 0:
            direction = "UNDER"
        else:
            direction = "neutral"

        evidence = " | ".join(factors) if factors else "No significant environmental factors"
        if abs(strength) >= 0.03:
            evidence += f" → {direction}"

        return SignalResult(
            signal_type=self.name,
            strength=self._clamp(strength),
            confidence=confidence,
            evidence=evidence,
            raw_data={
                'is_b2b': ctx.is_b2b,
                'is_3_in_4': ctx.is_3_in_4,
                'is_home': ctx.is_home,
                'spread': ctx.spread,
                'factors': factors,
                'total_impact_pct': round(total_impact * 100, 2),
            }
        )

    def _blowout_risk(self, spread: float, is_home: bool) -> float:
        """
        Assess blowout risk based on spread.

        Large favorites risk garbage time (reduced star minutes).
        Large underdogs might get blown out (reduced star minutes).
        """
        # Adjust spread to "our team" perspective
        team_spread = spread if is_home else -spread

        # Big favorite (spread < -10)
        if team_spread < -12:
            # High risk of blowout - stars might rest 4th quarter
            return -0.10
        elif team_spread < -8:
            return -0.05

        # Big underdog (spread > 10)
        if team_spread > 12:
            # Team might get blown out
            return -0.08
        elif team_spread > 8:
            return -0.04

        return 0.0

    def _calculate_confidence(self, ctx: PropContext) -> float:
        """
        Calculate confidence in environmental signal.
        """
        confidence = 0.5

        # B2B impact is well-documented
        if ctx.is_b2b:
            confidence += 0.15

        # High value players more likely affected by rest
        if ctx.is_high_value:
            confidence += 0.1

        # Have spread data for blowout analysis
        if ctx.spread is not None:
            confidence += 0.05

        return self._clamp(confidence, 0.0, 1.0)
