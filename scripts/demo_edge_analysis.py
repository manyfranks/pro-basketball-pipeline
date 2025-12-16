#!/usr/bin/env python3
"""
Demo: NBA SGP Edge Analysis

Shows how to use the edge calculator to analyze player props.
"""

import sys
import logging
from pathlib import Path

# Add project root to path for proper imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.signals import PropContext
from src.edge_calculator import EdgeCalculator

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def create_sample_context():
    """Create a sample prop context for demonstration."""
    return PropContext(
        # Player info
        player_id=2544,
        player_name="LeBron James",
        team="LAL",
        team_id=1610612747,

        # Prop details
        stat_type="points",
        line=24.5,
        over_odds=-115,
        under_odds=-105,

        # Season stats
        games_played=25,
        minutes_per_game=35.2,
        usage_pct=31.5,
        season_avg=23.8,

        # Recent stats (L5)
        recent_avg=27.2,  # Hot streak
        recent_minutes=36.0,

        # Opponent context
        opponent_team="DET",
        opponent_team_id=1610612765,
        opponent_def_rating=118.5,  # Bad defense
        opponent_pace=101.2,

        # Game context
        game_date="2024-12-15",
        is_home=True,
        is_b2b=False,
        is_3_in_4=False,
        game_total=232.5,  # High total
        spread=-8.5,

        # Flags
        is_high_value=True,
    )


def main():
    print("=" * 60)
    print("NBA SGP Edge Analysis Demo")
    print("=" * 60)

    # Create edge calculator
    calculator = EdgeCalculator()

    # Create sample prop
    ctx = create_sample_context()

    print(f"\nAnalyzing: {ctx.player_name} {ctx.stat_type} O/U {ctx.line}")
    print(f"Season avg: {ctx.season_avg}, Recent avg: {ctx.recent_avg}")
    print(f"Opponent: {ctx.opponent_team} (DEF_RTG: {ctx.opponent_def_rating})")
    print("-" * 60)

    # Calculate edge
    result = calculator.calculate_edge(ctx)

    # Print results
    print(f"\nEDGE SCORE: {result.edge_score:+.4f}")
    print(f"DIRECTION: {result.direction.upper()}")
    print(f"CONFIDENCE: {result.confidence:.2%}")
    print(f"RECOMMENDATION: {result.recommendation.upper()}")
    print(f"EXPECTED VALUE: {result.expected_value:+.4f}")

    print("\n" + "-" * 60)
    print("SIGNAL BREAKDOWN:")
    print("-" * 60)

    for signal in result.signals:
        direction = "↑" if signal.strength > 0 else "↓" if signal.strength < 0 else "→"
        print(f"\n{signal.signal_type.upper()} ({signal.confidence:.0%} conf)")
        print(f"  Strength: {signal.strength:+.4f} {direction}")
        print(f"  Evidence: {signal.evidence}")

    print("\n" + "=" * 60)
    print("Analysis complete!")


if __name__ == "__main__":
    main()
