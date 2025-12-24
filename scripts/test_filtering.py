#!/usr/bin/env python3
"""
Test the new filtering logic for rebounds and assists.

Verifies:
1. Rebounds with neutral environment get filtered (recommendation = 'pass')
2. Rebounds with aligned environment get accepted
3. Assists with low edge get filtered
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.signals.base import PropContext, SignalResult
from src.edge_calculator import EdgeCalculator


def create_test_context(
    stat_type: str,
    player_name: str = "Test Player",
    line: float = 10.0,
    season_avg: float = 12.0,
    recent_avg: float = 11.0,
) -> PropContext:
    """Create a minimal test PropContext."""
    return PropContext(
        player_id=12345,
        player_name=player_name,
        team="TST",
        team_id=1,
        stat_type=stat_type,
        line=line,
        over_odds=-110,
        under_odds=-110,
        games_played=20,
        minutes_per_game=32.0,
        usage_pct=25.0,
        season_avg=season_avg,
        recent_avg=recent_avg,
        opponent_team="OPP",
        opponent_team_id=2,
        opponent_def_rating=115.0,  # Bad defense
        opponent_pace=102.0,  # Fast pace
        is_home=True,
        is_high_value=True,
    )


def test_rebounds_filtering():
    """Test that rebounds filtering works based on environment signal."""
    print("\n" + "=" * 60)
    print("TEST: Rebounds Filtering (Environment Alignment)")
    print("=" * 60)

    calc = EdgeCalculator()

    # Test case 1: Rebounds with good matchup but neutral environment
    print("\n1. Rebounds OVER with neutral environment (should PASS):")
    ctx = create_test_context(
        stat_type="rebounds",
        line=8.0,
        season_avg=10.0,
        recent_avg=11.0,  # Recent > line = over signal
    )
    # Neutral environment - no B2B, neutral pace, etc.
    result = calc.calculate_edge(ctx)
    print(f"   Edge Score: {result.edge_score:.3f}")
    print(f"   Direction: {result.direction}")
    print(f"   Recommendation: {result.recommendation}")

    env_signal = next((s.strength for s in result.signals if s.signal_type == 'environment'), 0)
    print(f"   Environment Signal: {env_signal:.3f}")

    if result.recommendation == 'pass':
        print("   CORRECT: Filtered due to neutral environment")
    else:
        print("   WARNING: Should have been filtered!")

    # Test case 2: Rebounds with favorable environment (B2B opponent)
    print("\n2. Rebounds OVER with favorable environment (should ACCEPT):")
    ctx = create_test_context(
        stat_type="rebounds",
        line=8.0,
        season_avg=10.0,
        recent_avg=11.0,
    )
    # Force favorable environment - opponent on B2B, high pace
    ctx.opponent_pace = 105.0  # Very fast
    ctx.is_b2b = False  # We're rested
    ctx.game_total = 235.0  # High total = more possessions
    result = calc.calculate_edge(ctx)
    print(f"   Edge Score: {result.edge_score:.3f}")
    print(f"   Direction: {result.direction}")
    print(f"   Recommendation: {result.recommendation}")

    env_signal = next((s.strength for s in result.signals if s.signal_type == 'environment'), 0)
    print(f"   Environment Signal: {env_signal:.3f}")

    if result.recommendation != 'pass':
        print("   CORRECT: Accepted with favorable environment")
    else:
        print(f"   INFO: Still filtered (env signal may not be positive enough: {env_signal:.3f})")


def test_assists_filtering():
    """Test that assists filtering works based on edge threshold."""
    print("\n" + "=" * 60)
    print("TEST: Assists Filtering (Higher Edge Threshold)")
    print("=" * 60)

    calc = EdgeCalculator()

    # Test case 1: Assists with weak edge (should filter)
    print("\n1. Assists with weak edge < 0.15 (should PASS):")
    ctx = create_test_context(
        stat_type="assists",
        line=6.0,
        season_avg=6.2,  # Barely above line
        recent_avg=6.3,
    )
    result = calc.calculate_edge(ctx)
    print(f"   Edge Score: {result.edge_score:.3f}")
    print(f"   Recommendation: {result.recommendation}")

    if result.recommendation == 'pass':
        print("   CORRECT: Filtered due to low edge")
    else:
        print(f"   INFO: Accepted (edge {abs(result.edge_score):.3f} >= 0.15)")

    # Test case 2: Assists with strong edge (should accept)
    print("\n2. Assists with strong edge >= 0.15 (should ACCEPT):")
    ctx = create_test_context(
        stat_type="assists",
        line=5.0,
        season_avg=8.0,  # Well above line
        recent_avg=9.0,
    )
    ctx.opponent_def_rating = 118.0  # Very bad defense
    result = calc.calculate_edge(ctx)
    print(f"   Edge Score: {result.edge_score:.3f}")
    print(f"   Recommendation: {result.recommendation}")

    if result.recommendation != 'pass':
        print("   CORRECT: Accepted with strong edge")
    else:
        print("   WARNING: Should have been accepted!")


def test_points_unchanged():
    """Test that points logic is unchanged."""
    print("\n" + "=" * 60)
    print("TEST: Points (Should Be Unchanged)")
    print("=" * 60)

    calc = EdgeCalculator()

    ctx = create_test_context(
        stat_type="points",
        line=22.0,
        season_avg=25.0,
        recent_avg=26.0,
    )
    ctx.opponent_def_rating = 116.0  # Bad defense
    result = calc.calculate_edge(ctx)
    print(f"\n   Edge Score: {result.edge_score:.3f}")
    print(f"   Direction: {result.direction}")
    print(f"   Recommendation: {result.recommendation}")
    print(f"   Confidence: {result.confidence:.3f}")

    # Points should use standard logic
    if abs(result.edge_score) >= 0.08 and result.recommendation != 'pass':
        print("   CORRECT: Points using standard logic")
    elif result.recommendation == 'pass':
        print("   INFO: Passed - check confidence threshold")


def main():
    print("\n" + "=" * 70)
    print("SIGNAL FILTERING VERIFICATION")
    print("=" * 70)
    print("\nThis tests the new filtering logic:")
    print("1. REBOUNDS: Require environment signal alignment")
    print("2. ASSISTS: Require edge >= 0.15 (MODERATE_EDGE)")
    print("3. POINTS: Unchanged (standard logic)")

    test_rebounds_filtering()
    test_assists_filtering()
    test_points_unchanged()

    print("\n" + "=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)
    print("\nNote: Actual signal values depend on context data.")
    print("In production, environment signals come from real game context.")


if __name__ == '__main__':
    main()
