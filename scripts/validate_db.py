#!/usr/bin/env python3
"""
Database Validation Script

Queries the NBA SGP tables and views directly to identify data issues.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# Load env
load_dotenv(project_root / ".env")

from supabase import create_client

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("ERROR: SUPABASE_URL and SUPABASE_KEY required")
    sys.exit(1)

client = create_client(url, key)

print("=" * 70)
print("NBA SGP DATABASE VALIDATION")
print("=" * 70)

# 1. Count records in each table
print("\n### TABLE COUNTS ###")
tables = ["nba_sgp_parlays", "nba_sgp_legs", "nba_sgp_settlements"]
for table in tables:
    result = client.table(table).select("id", count="exact").execute()
    print(f"  {table}: {result.count} records")

# 2. Check settlements data
print("\n### SETTLEMENTS TABLE ###")
settlements = client.table("nba_sgp_settlements").select("*").execute()
print(f"  Total settlements: {len(settlements.data)}")

if settlements.data:
    results = {}
    for s in settlements.data:
        r = s.get("result")
        results[r] = results.get(r, 0) + 1
    print(f"  By result: {results}")

    # Check legs_hit vs total_legs
    print("\n  Settlement legs_hit vs total_legs:")
    for s in settlements.data[:10]:
        legs_hit = s.get("legs_hit", 0)
        total_legs = s.get("total_legs", 0)
        flag = " ⚠️ IMPOSSIBLE" if legs_hit > total_legs else ""
        print(f"    parlay {s['parlay_id'][:8]}...: {legs_hit}/{total_legs}{flag}")

# 3. Check legs table - count results
print("\n### LEGS TABLE - RESULT DISTRIBUTION ###")
legs = client.table("nba_sgp_legs").select("id, result, parlay_id").execute()
print(f"  Total legs: {len(legs.data)}")

leg_results = {}
for leg in legs.data:
    r = leg.get("result")
    leg_results[r] = leg_results.get(r, 0) + 1
print(f"  By result: {leg_results}")

# 4. Compare legs per parlay
print("\n### LEGS PER PARLAY VALIDATION ###")
parlay_leg_counts = {}
for leg in legs.data:
    pid = leg["parlay_id"]
    parlay_leg_counts[pid] = parlay_leg_counts.get(pid, 0) + 1

# Get parlay total_legs field
parlays = client.table("nba_sgp_parlays").select("id, total_legs, game_date").execute()
parlay_totals = {p["id"]: p for p in parlays.data}

mismatches = []
for pid, actual_count in parlay_leg_counts.items():
    expected = parlay_totals.get(pid, {}).get("total_legs", 0)
    if actual_count != expected:
        mismatches.append((pid, actual_count, expected))

if mismatches:
    print(f"  ⚠️ Found {len(mismatches)} parlays where actual leg count != total_legs field:")
    for pid, actual, expected in mismatches[:5]:
        print(f"    {pid[:8]}...: actual={actual}, field={expected}")
else:
    print("  ✓ All parlays have matching leg counts")

# 5. Check leg wins vs settlement legs_hit
print("\n### LEG WINS VS SETTLEMENT LEGS_HIT ###")
for s in settlements.data[:10]:
    pid = s["parlay_id"]
    settlement_legs_hit = s.get("legs_hit", 0)

    # Count actual leg wins for this parlay
    parlay_legs = [l for l in legs.data if l["parlay_id"] == pid]
    actual_wins = sum(1 for l in parlay_legs if l.get("result") == "WIN")

    flag = " ⚠️ MISMATCH" if actual_wins != settlement_legs_hit else " ✓"
    print(f"  {pid[:8]}...: settlement says {settlement_legs_hit}, actual leg WINs = {actual_wins}{flag}")

# 6. Query the views
print("\n### VIEW: v_nba_sgp_daily_summary ###")
try:
    daily = client.table("v_nba_sgp_daily_summary").select("*").limit(10).execute()
    for row in daily.data:
        legs_hit = row.get("legs_hit", 0)
        total_legs = row.get("total_legs", 0)
        flag = " ⚠️ IMPOSSIBLE" if legs_hit > total_legs else ""
        print(f"  {row.get('game_date')} {row.get('parlay_type')}: "
              f"{legs_hit}/{total_legs} legs, "
              f"{row.get('parlays_won', 0)}/{row.get('total_parlays', 0)} parlays{flag}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n### VIEW: v_nba_sgp_season_summary ###")
try:
    season = client.table("v_nba_sgp_season_summary").select("*").execute()
    for row in season.data:
        print(f"  Season {row.get('season')} {row.get('season_type')}: "
              f"{row.get('total_legs_hit', 0)}/{row.get('total_legs', 0)} legs, "
              f"{row.get('parlays_won', 0)}/{row.get('total_parlays', 0)} parlays, "
              f"hit rate: {row.get('leg_hit_rate', 0)}%")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n### VIEW: v_nba_sgp_prop_performance ###")
try:
    props = client.table("v_nba_sgp_prop_performance").select("*").execute()
    for row in props.data:
        print(f"  {row.get('stat_type')} {row.get('direction')}: "
              f"{row.get('wins', 0)}/{row.get('total_picks', 0)} = {row.get('win_rate', 0)}%")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "=" * 70)
print("VALIDATION COMPLETE")
print("=" * 70)
