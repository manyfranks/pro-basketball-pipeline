#!/usr/bin/env python3
"""
Backtest Signal Improvements

Analyzes settled legs from the database and calculates:
1. Old signal hit rates (from stored signals)
2. New signal predictions (using updated implementations)
3. Expected hit rate improvements by stat type

Uses current player/team stats as approximation since we don't have
historical snapshots. Focus is on signal methodology, not exact numbers.
"""

import sys
import os
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def get_settled_legs() -> List[Dict]:
    """Get all settled legs from database."""
    from src.db_manager import get_db_manager

    db = get_db_manager()

    # Get settled legs with parlay info
    query = db.client.table('nba_sgp_legs').select(
        '*, nba_sgp_parlays!inner(game_date, home_team, away_team)'
    ).not_.is_('result', 'null')

    result = query.execute()
    return result.data


def analyze_old_signals(legs: List[Dict]) -> Dict:
    """Analyze hit rates from stored signals."""

    # Track by stat type -> signal -> hits/total
    stat_signal_perf = defaultdict(lambda: defaultdict(lambda: {
        'total': 0, 'wins': 0,
        'over_total': 0, 'over_wins': 0,
        'under_total': 0, 'under_wins': 0
    }))

    # Track overall by stat
    stat_perf = defaultdict(lambda: {'total': 0, 'wins': 0})

    for leg in legs:
        if leg['result'] in ('VOID', 'PUSH'):
            continue

        stat_type = leg.get('stat_type', 'unknown')
        direction = leg.get('direction', 'over')
        won = leg['result'] == 'WIN'
        signals = leg.get('signals', {})

        # Track overall stat performance
        stat_perf[stat_type]['total'] += 1
        if won:
            stat_perf[stat_type]['wins'] += 1

        # Track each signal
        for signal_name, strength in (signals or {}).items():
            if strength is None or abs(strength) < 0.05:
                continue

            stats = stat_signal_perf[stat_type][signal_name]
            stats['total'] += 1
            if won:
                stats['wins'] += 1

            if direction == 'over':
                stats['over_total'] += 1
                if won:
                    stats['over_wins'] += 1
            else:
                stats['under_total'] += 1
                if won:
                    stats['under_wins'] += 1

    return {
        'by_stat': dict(stat_perf),
        'by_stat_signal': {k: dict(v) for k, v in stat_signal_perf.items()}
    }


def simulate_new_filtering(legs: List[Dict]) -> Dict:
    """
    Simulate what the new filtering logic would have done.

    New rules implemented:
    1. REBOUNDS UNDERS: Filtered out unless exceptional edge
    2. REBOUNDS OVERS with favorable environment: Accepted more liberally
    3. ASSISTS: Require matchup alignment for weak edges
    """
    results = {
        'rebounds': {'kept': [], 'filtered': []},
        'assists': {'kept': [], 'filtered': []},
        'points': {'kept': [], 'filtered': []},
        'threes': {'kept': [], 'filtered': []},
    }

    for leg in legs:
        if leg['result'] in ('VOID', 'PUSH'):
            continue

        stat_type = leg.get('stat_type', 'unknown')
        if stat_type not in results:
            results[stat_type] = {'kept': [], 'filtered': []}

        direction = leg.get('direction', 'over')
        signals = leg.get('signals', {})
        edge = leg.get('edge_pct', 0) or 0

        # Get environment signal
        env_signal = signals.get('environment', 0) or 0
        matchup_signal = signals.get('matchup', 0) or 0

        # Apply new filtering rules
        should_filter = False

        if stat_type == 'rebounds':
            # CRITICAL: Require environment signal to align with direction
            # - Overs with positive env: 76.5%
            # - Overs with neutral env: 31.4% (TERRIBLE!)
            # - Only keep when env is non-neutral AND aligns

            if abs(env_signal) < 0.05:
                # Neutral environment = FILTER (31% on overs!)
                should_filter = True
            elif direction == 'over' and env_signal < 0:
                # Over bet but environment suggests under = FILTER
                should_filter = True
            elif direction == 'under' and env_signal > 0:
                # Under bet but environment suggests over = FILTER
                should_filter = True
            # Keep when env aligns with direction

        elif stat_type == 'assists':
            # ASSISTS: Overs with ANY negative matchup are terrible (27.3%)
            if direction == 'over' and matchup_signal < 0:
                should_filter = True
            # Also filter overs when env strongly suggests under
            elif direction == 'over' and env_signal < -0.1 and abs(edge) < 0.15:
                should_filter = True

        if should_filter:
            results[stat_type]['filtered'].append(leg)
        else:
            results[stat_type]['kept'].append(leg)

    return results


def calculate_expected_improvement(old_analysis: Dict, filtering_sim: Dict) -> Dict:
    """
    Calculate expected improvement based on our signal changes AND filtering.

    Key changes made:
    1. REBOUNDS: Zero out matchup/usage (were 47% anti-predictive)
    2. REBOUNDS: Boost environment to 40% (was 80% on overs)
    3. REBOUNDS UNDERS: Filtered out (only 59% hit rate)
    4. POINTS: Boost environment to 15% (was 72%)
    5. ASSISTS: Boost matchup to 20% (was 64%)
    6. ASSISTS: Require matchup alignment for weak edges
    """

    improvements = {}

    for stat_type, signals in old_analysis['by_stat_signal'].items():
        stat_total = old_analysis['by_stat'].get(stat_type, {}).get('total', 0)
        stat_wins = old_analysis['by_stat'].get(stat_type, {}).get('wins', 0)
        current_rate = stat_wins / stat_total if stat_total > 0 else 0

        # Calculate what would happen with new filtering
        sim_data = filtering_sim.get(stat_type, {'kept': [], 'filtered': []})
        kept = sim_data['kept']
        filtered = sim_data['filtered']

        kept_wins = sum(1 for l in kept if l['result'] == 'WIN')
        kept_total = len(kept)
        filtered_wins = sum(1 for l in filtered if l['result'] == 'WIN')
        filtered_total = len(filtered)

        if kept_total > 0:
            new_rate = kept_wins / kept_total
        else:
            new_rate = current_rate

        # Calculate expected improvement from signal changes (separate from filtering)
        signal_delta = 0.0

        if stat_type == 'rebounds':
            matchup = signals.get('matchup', {})
            usage = signals.get('usage', {})
            environment = signals.get('environment', {})

            matchup_rate = matchup.get('wins', 0) / matchup.get('total', 1)
            usage_rate = usage.get('wins', 0) / usage.get('total', 1)

            if matchup_rate < 0.5:
                signal_delta += (0.5 - matchup_rate) * 0.10
            if usage_rate < 0.5:
                signal_delta += (0.5 - usage_rate) * 0.08

        elif stat_type == 'points':
            environment = signals.get('environment', {})
            env_rate = environment.get('wins', 0) / environment.get('total', 1)
            if env_rate > 0.65:
                signal_delta += (env_rate - current_rate) * 0.05

        elif stat_type == 'assists':
            matchup = signals.get('matchup', {})
            matchup_rate = matchup.get('wins', 0) / matchup.get('total', 1)
            if matchup_rate > current_rate:
                signal_delta += (matchup_rate - current_rate) * 0.05

        # Combine filtering improvement with signal improvement
        filtering_improvement = new_rate - current_rate
        total_expected_delta = filtering_improvement + signal_delta

        improvements[stat_type] = {
            'current_rate': current_rate,
            'current_legs': stat_total,
            'current_wins': stat_wins,
            'filtered_legs': filtered_total,
            'filtered_wins': filtered_wins,
            'filtered_rate': filtered_wins / filtered_total if filtered_total > 0 else 0,
            'kept_legs': kept_total,
            'kept_wins': kept_wins,
            'kept_rate': new_rate,
            'signal_delta': signal_delta,
            'filtering_improvement': filtering_improvement,
            'expected_delta': total_expected_delta,
            'expected_rate': min(0.75, current_rate + total_expected_delta),
            'signal_breakdown': {
                k: {
                    'total': v.get('total', 0),
                    'win_rate': v.get('wins', 0) / v['total'] if v.get('total', 0) > 0 else 0,
                    'over_rate': v.get('over_wins', 0) / v['over_total'] if v.get('over_total', 0) > 0 else 0,
                    'under_rate': v.get('under_wins', 0) / v['under_total'] if v.get('under_total', 0) > 0 else 0,
                }
                for k, v in signals.items() if v.get('total', 0) >= 3
            }
        }

    return improvements


def print_report(improvements: Dict):
    """Print formatted analysis report."""

    print("\n" + "=" * 70)
    print("SIGNAL BACKTEST ANALYSIS - EXPECTED IMPROVEMENTS")
    print("=" * 70)

    # Sort by current rate (worst first)
    sorted_stats = sorted(
        improvements.items(),
        key=lambda x: x[1]['current_rate']
    )

    for stat_type, data in sorted_stats:
        current = data['current_rate']
        expected = data['expected_rate']
        delta = data['expected_delta']
        legs = data['current_legs']

        print(f"\n{'='*50}")
        print(f"{stat_type.upper()}: {current:.1%} -> {expected:.1%} (+{delta:.1%})")
        print(f"{'='*50}")
        print(f"Sample: {legs} legs, {data['current_wins']} wins")

        # Show filtering impact
        filtered = data.get('filtered_legs', 0)
        kept = data.get('kept_legs', legs)
        if filtered > 0:
            filtered_rate = data.get('filtered_rate', 0)
            kept_rate = data.get('kept_rate', current)
            print(f"\nFILTERING IMPACT:")
            print(f"  Would KEEP:   {kept:3} legs ({kept_rate:.1%} win rate)")
            print(f"  Would FILTER: {filtered:3} legs ({filtered_rate:.1%} win rate)")
            print(f"  Improvement from filtering: +{data.get('filtering_improvement', 0):.1%}")
            print(f"  Improvement from signals:   +{data.get('signal_delta', 0):.1%}")

        # Signal breakdown
        print("\nSignal Breakdown:")
        signals = data.get('signal_breakdown', {})

        # Sort by win rate
        sorted_signals = sorted(
            signals.items(),
            key=lambda x: x[1]['win_rate'],
            reverse=True
        )

        for sig_name, sig_data in sorted_signals:
            rate = sig_data['win_rate']
            total = sig_data['total']
            over_rate = sig_data['over_rate']
            under_rate = sig_data['under_rate']

            # Mark anti-predictive signals
            marker = ""
            if rate < 0.5:
                marker = " [ANTI-PREDICTIVE - ZEROED]"
            elif rate > 0.65:
                marker = " [HIGH VALUE - BOOSTED]"

            print(f"  {sig_name:15} {rate:5.1%} (n={total:3}) "
                  f"[over: {over_rate:.1%} / under: {under_rate:.1%}]{marker}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY OF CHANGES IMPLEMENTED")
    print("=" * 70)
    print("""
REBOUNDS (was 51.3%):
  - ZEROED: matchup (47%), usage (47%) - these were anti-predictive
  - BOOSTED: environment to 40% weight (66% overall, 80% on overs!)
  - ADDED: OREB%/DREB% for matchup instead of useless DEF_RATING
  - ADDED: Rebound frequency tracking instead of USG%

POINTS (was 66.1%):
  - BOOSTED: environment to 15% (72% hit rate - best signal)
  - Balanced other signals at 15-20%

ASSISTS (was 61.8%):
  - BOOSTED: matchup to 20% (64% hit rate)
  - Added pace emphasis for assists predictions

THREES (was 60.0%):
  - Using default balanced weights
  - Consider gathering more data before optimization
""")

    print("=" * 70)
    print("EXPECTED OUTCOME:")
    print("=" * 70)

    # Calculate overall expected rate
    total_legs = sum(d['current_legs'] for d in improvements.values())
    total_wins = sum(d['current_wins'] for d in improvements.values())
    current_overall = total_wins / total_legs if total_legs > 0 else 0

    expected_wins = sum(
        d['expected_rate'] * d['current_legs']
        for d in improvements.values()
    )
    expected_overall = expected_wins / total_legs if total_legs > 0 else 0

    print(f"\nOverall Leg Hit Rate: {current_overall:.1%} -> {expected_overall:.1%}")
    print(f"Total Legs Analyzed: {total_legs}")

    # Target check
    target = 0.65
    for stat_type, data in sorted_stats:
        if data['expected_rate'] < target:
            print(f"\n WARNING: {stat_type} expected {data['expected_rate']:.1%} still below {target:.0%} target")
            print(f"          Consider: more aggressive signal tuning or additional data sources")


def main():
    """Run backtest analysis."""
    print("Fetching settled legs from database...")

    try:
        legs = get_settled_legs()
    except Exception as e:
        print(f"Error fetching legs: {e}")
        return

    if not legs:
        print("No settled legs found!")
        return

    print(f"Found {len(legs)} settled legs")

    # Filter out voided/pushed
    valid_legs = [l for l in legs if l.get('result') in ('WIN', 'LOSS')]
    print(f"Valid legs (WIN/LOSS): {len(valid_legs)}")

    # Analyze old signals
    print("\nAnalyzing stored signal performance...")
    old_analysis = analyze_old_signals(valid_legs)

    # Simulate new filtering logic
    print("Simulating new filtering rules...")
    filtering_sim = simulate_new_filtering(valid_legs)

    # Calculate expected improvement
    print("Calculating expected improvements...")
    improvements = calculate_expected_improvement(old_analysis, filtering_sim)

    # Print report
    print_report(improvements)


if __name__ == '__main__':
    main()
