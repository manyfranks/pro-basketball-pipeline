#!/usr/bin/env python3
"""
Deep dive into assists performance to find optimization opportunities.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db_manager import get_db_manager


def analyze_assists():
    db = get_db_manager()

    # Get all assists legs
    query = db.client.table('nba_sgp_legs').select('*').eq(
        'stat_type', 'assists'
    ).not_.is_('result', 'null')

    legs = query.execute().data

    print(f"\n{'='*60}")
    print("ASSISTS DEEP DIVE")
    print(f"{'='*60}")
    print(f"\nTotal assists legs: {len(legs)}")

    # Filter valid
    valid = [l for l in legs if l['result'] in ('WIN', 'LOSS')]
    print(f"Valid (WIN/LOSS): {len(valid)}")

    # Split by direction
    overs = [l for l in valid if l.get('direction') == 'over']
    unders = [l for l in valid if l.get('direction') == 'under']

    over_wins = sum(1 for l in overs if l['result'] == 'WIN')
    under_wins = sum(1 for l in unders if l['result'] == 'WIN')

    print(f"\nOVERS:  {len(overs)} legs, {over_wins} wins ({over_wins/len(overs):.1%})" if overs else "OVERS: 0 legs")
    print(f"UNDERS: {len(unders)} legs, {under_wins} wins ({under_wins/len(unders):.1%})" if unders else "UNDERS: 0 legs")

    def calc_rate(legs_list):
        if not legs_list:
            return 0, 0, 0
        wins = sum(1 for l in legs_list if l['result'] == 'WIN')
        return len(legs_list), wins, wins/len(legs_list)

    # Analyze by MATCHUP signal (best signal at 64.3%)
    print(f"\n{'='*60}")
    print("MATCHUP SIGNAL ANALYSIS")
    print(f"{'='*60}")

    for direction_name, direction_legs in [("OVERS", overs), ("UNDERS", unders)]:
        print(f"\n{direction_name}:")

        pos = [l for l in direction_legs if (l.get('signals', {}).get('matchup') or 0) > 0.1]
        neg = [l for l in direction_legs if (l.get('signals', {}).get('matchup') or 0) < -0.1]
        neutral = [l for l in direction_legs if abs(l.get('signals', {}).get('matchup') or 0) <= 0.1]

        n, w, r = calc_rate(pos)
        print(f"  Matchup POSITIVE (>0.1):  {n:3} legs, {w:3} wins ({r:.1%})")
        n, w, r = calc_rate(neg)
        print(f"  Matchup NEGATIVE (<-0.1): {n:3} legs, {w:3} wins ({r:.1%})")
        n, w, r = calc_rate(neutral)
        print(f"  Matchup NEUTRAL:          {n:3} legs, {w:3} wins ({r:.1%})")

    # Check alignment
    print(f"\n{'='*60}")
    print("MATCHUP ALIGNMENT ANALYSIS")
    print(f"{'='*60}")

    overs_aligned = [l for l in overs if (l.get('signals', {}).get('matchup') or 0) > 0]
    overs_misaligned = [l for l in overs if (l.get('signals', {}).get('matchup') or 0) < 0]
    unders_aligned = [l for l in unders if (l.get('signals', {}).get('matchup') or 0) < 0]
    unders_misaligned = [l for l in unders if (l.get('signals', {}).get('matchup') or 0) > 0]

    n, w, r = calc_rate(overs_aligned)
    print(f"OVERS with positive matchup (aligned):   {n:3} legs, {w:3} wins ({r:.1%})")
    n, w, r = calc_rate(overs_misaligned)
    print(f"OVERS with negative matchup (misaligned): {n:3} legs, {w:3} wins ({r:.1%})")
    n, w, r = calc_rate(unders_aligned)
    print(f"UNDERS with negative matchup (aligned):   {n:3} legs, {w:3} wins ({r:.1%})")
    n, w, r = calc_rate(unders_misaligned)
    print(f"UNDERS with positive matchup (misaligned): {n:3} legs, {w:3} wins ({r:.1%})")

    # Optimal: aligned picks
    aligned = overs_aligned + unders_aligned
    aligned_wins = sum(1 for l in aligned if l['result'] == 'WIN')
    aligned_rate = aligned_wins / len(aligned) if aligned else 0

    print(f"\n{'='*60}")
    print("OPTIMAL STRATEGY")
    print(f"{'='*60}")
    print(f"\nIf we ONLY took picks where matchup aligned with direction:")
    print(f"  Legs: {len(aligned)}")
    print(f"  Wins: {aligned_wins}")
    print(f"  Win Rate: {aligned_rate:.1%}")

    # Multi-signal analysis
    print(f"\n{'='*60}")
    print("MULTI-SIGNAL ANALYSIS")
    print(f"{'='*60}")

    # Strong matchup AND environment aligned
    strong_picks = []
    for l in valid:
        signals = l.get('signals', {})
        matchup = signals.get('matchup') or 0
        env = signals.get('environment') or 0
        direction = l.get('direction', 'over')

        matchup_aligned = (direction == 'over' and matchup > 0) or (direction == 'under' and matchup < 0)
        env_aligned = (direction == 'over' and env > 0) or (direction == 'under' and env < 0)

        if matchup_aligned and env_aligned:
            strong_picks.append(l)

    n, w, r = calc_rate(strong_picks)
    print(f"Both matchup AND environment aligned: {n:3} legs, {w:3} wins ({r:.1%})")

    # Matchup aligned, env neutral or aligned
    relaxed_picks = []
    for l in valid:
        signals = l.get('signals', {})
        matchup = signals.get('matchup') or 0
        env = signals.get('environment') or 0
        direction = l.get('direction', 'over')

        matchup_aligned = (direction == 'over' and matchup > 0.05) or (direction == 'under' and matchup < -0.05)
        env_not_against = not ((direction == 'over' and env < -0.1) or (direction == 'under' and env > 0.1))

        if matchup_aligned and env_not_against:
            relaxed_picks.append(l)

    n, w, r = calc_rate(relaxed_picks)
    print(f"Matchup aligned, env not against:     {n:3} legs, {w:3} wins ({r:.1%})")


if __name__ == '__main__':
    analyze_assists()
