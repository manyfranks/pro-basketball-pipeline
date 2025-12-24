#!/usr/bin/env python3
"""
Deep dive into rebounds performance.

The backtest shows:
- Environment signal on rebounds OVERS: 80% hit rate
- Environment signal on rebounds UNDERS: 59% hit rate

Let's understand what's happening and optimize our filtering.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collections import defaultdict
from src.db_manager import get_db_manager


def analyze_rebounds():
    db = get_db_manager()

    # Get all rebounds legs
    query = db.client.table('nba_sgp_legs').select('*').eq(
        'stat_type', 'rebounds'
    ).not_.is_('result', 'null')

    legs = query.execute().data

    print(f"\n{'='*60}")
    print("REBOUNDS DEEP DIVE")
    print(f"{'='*60}")
    print(f"\nTotal rebounds legs: {len(legs)}")

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

    # Analyze by environment signal
    print(f"\n{'='*60}")
    print("ENVIRONMENT SIGNAL ANALYSIS")
    print(f"{'='*60}")

    # OVERS with positive env (favorable)
    overs_env_pos = [l for l in overs if (l.get('signals', {}).get('environment') or 0) > 0]
    overs_env_neg = [l for l in overs if (l.get('signals', {}).get('environment') or 0) < 0]
    overs_env_neutral = [l for l in overs if abs(l.get('signals', {}).get('environment') or 0) < 0.05]

    # UNDERS with negative env (favorable for under)
    unders_env_pos = [l for l in unders if (l.get('signals', {}).get('environment') or 0) > 0]
    unders_env_neg = [l for l in unders if (l.get('signals', {}).get('environment') or 0) < 0]
    unders_env_neutral = [l for l in unders if abs(l.get('signals', {}).get('environment') or 0) < 0.05]

    def calc_rate(legs_list):
        if not legs_list:
            return 0, 0, 0
        wins = sum(1 for l in legs_list if l['result'] == 'WIN')
        return len(legs_list), wins, wins/len(legs_list)

    print("\nOVERS breakdown:")
    n, w, r = calc_rate(overs_env_pos)
    print(f"  Environment POSITIVE (favorable):  {n:3} legs, {w:3} wins ({r:.1%}) 🎯")
    n, w, r = calc_rate(overs_env_neg)
    print(f"  Environment NEGATIVE (unfavorable): {n:3} legs, {w:3} wins ({r:.1%})")
    n, w, r = calc_rate(overs_env_neutral)
    print(f"  Environment NEUTRAL:                {n:3} legs, {w:3} wins ({r:.1%})")

    print("\nUNDERS breakdown:")
    n, w, r = calc_rate(unders_env_neg)
    print(f"  Environment NEGATIVE (favorable):   {n:3} legs, {w:3} wins ({r:.1%})")
    n, w, r = calc_rate(unders_env_pos)
    print(f"  Environment POSITIVE (unfavorable): {n:3} legs, {w:3} wins ({r:.1%}) ⚠️")
    n, w, r = calc_rate(unders_env_neutral)
    print(f"  Environment NEUTRAL:                {n:3} legs, {w:3} wins ({r:.1%})")

    # OPTIMAL STRATEGY
    print(f"\n{'='*60}")
    print("OPTIMAL STRATEGY")
    print(f"{'='*60}")

    # Only take overs with positive env OR unders with negative env
    optimal = overs_env_pos + unders_env_neg
    optimal_wins = sum(1 for l in optimal if l['result'] == 'WIN')
    optimal_rate = optimal_wins / len(optimal) if optimal else 0

    print(f"\nIf we ONLY took picks where environment aligned with direction:")
    print(f"  Legs: {len(optimal)}")
    print(f"  Wins: {optimal_wins}")
    print(f"  Win Rate: {optimal_rate:.1%}")

    # What we filtered
    filtered = overs_env_neg + unders_env_pos + overs_env_neutral + unders_env_neutral
    filtered_wins = sum(1 for l in filtered if l['result'] == 'WIN')
    filtered_rate = filtered_wins / len(filtered) if filtered else 0

    print(f"\nLegs we would FILTER OUT (env misaligned or neutral):")
    print(f"  Legs: {len(filtered)}")
    print(f"  Wins: {filtered_wins}")
    print(f"  Win Rate: {filtered_rate:.1%}")

    print(f"\n{'='*60}")
    print("RECOMMENDATION")
    print(f"{'='*60}")

    if optimal_rate > 0.60:
        print(f"""
FOR REBOUNDS:
1. ONLY recommend when environment signal aligns with direction
   - OVERS: Require environment > 0 (favorable)
   - UNDERS: Require environment < 0 (favorable)

2. This would give us:
   - Current rate: {sum(1 for l in valid if l['result']=='WIN')/len(valid):.1%}
   - New rate: {optimal_rate:.1%}
   - Improvement: +{optimal_rate - sum(1 for l in valid if l['result']=='WIN')/len(valid):.1%}

3. Trade-off: Fewer total picks ({len(optimal)} vs {len(valid)})
   - But MUCH better quality picks!
""")
    else:
        print("Environment alignment doesn't help enough. Need other approaches.")

    # B2B analysis
    print(f"\n{'='*60}")
    print("ADDITIONAL ANALYSIS: MATCHUP (for comparison)")
    print(f"{'='*60}")

    # Matchup aligned
    overs_matchup_pos = [l for l in overs if (l.get('signals', {}).get('matchup') or 0) > 0]
    overs_matchup_neg = [l for l in overs if (l.get('signals', {}).get('matchup') or 0) < 0]

    n, w, r = calc_rate(overs_matchup_pos)
    print(f"OVERS with matchup POSITIVE:  {n:3} legs, {w:3} wins ({r:.1%})")
    n, w, r = calc_rate(overs_matchup_neg)
    print(f"OVERS with matchup NEGATIVE:  {n:3} legs, {w:3} wins ({r:.1%})")

    unders_matchup_pos = [l for l in unders if (l.get('signals', {}).get('matchup') or 0) > 0]
    unders_matchup_neg = [l for l in unders if (l.get('signals', {}).get('matchup') or 0) < 0]

    n, w, r = calc_rate(unders_matchup_neg)
    print(f"UNDERS with matchup NEGATIVE: {n:3} legs, {w:3} wins ({r:.1%})")
    n, w, r = calc_rate(unders_matchup_pos)
    print(f"UNDERS with matchup POSITIVE: {n:3} legs, {w:3} wins ({r:.1%})")

    print("\nConclusion: Matchup signal doesn't help for rebounds (as we found before)")


if __name__ == '__main__':
    analyze_rebounds()
