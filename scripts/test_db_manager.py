#!/usr/bin/env python3
"""
Test the NBA SGP Database Manager.

Run: python scripts/test_db_manager.py

This script:
1. Tests database connection
2. Creates a test parlay with legs
3. Reads back the parlay
4. Tests settlement flow
5. Cleans up test data
"""

import sys
import uuid
import logging
from pathlib import Path
from datetime import date

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.db_manager import get_db_manager, NBASGPDBManager

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def main():
    print("=" * 60)
    print("NBA SGP Database Manager Test")
    print("=" * 60)

    # Get database manager
    try:
        db = get_db_manager()
        print("\n[PASS] Database manager initialized")
    except Exception as e:
        print(f"\n[FAIL] Failed to initialize database manager: {e}")
        return

    # Test connection
    print("\n--- Testing Connection ---")
    if db.test_connection():
        print("[PASS] Database connection successful")
    else:
        print("[FAIL] Database connection failed")
        return

    # Create test parlay
    print("\n--- Testing Parlay Creation ---")
    test_game_id = f"test_game_{uuid.uuid4().hex[:8]}"
    test_parlay = {
        "parlay_type": "test_parlay",
        "game_id": test_game_id,
        "game_date": str(date.today()),
        "home_team": "LAL",
        "away_team": "BOS",
        "game_slot": "EVENING",
        "total_legs": 3,
        "combined_odds": 450,
        "implied_probability": 0.182,
        "thesis": "Test parlay for database manager verification",
        "season": 2026,
        "season_type": "regular",
        "legs": [
            {
                "leg_number": 1,
                "player_name": "LeBron James",
                "player_id": 2544,
                "team": "LAL",
                "position": "SF",
                "stat_type": "points",
                "line": 25.5,
                "direction": "over",
                "odds": -110,
                "edge_pct": 5.2,
                "confidence": 0.72,
                "model_probability": 0.55,
                "market_probability": 0.524,
                "primary_reason": "Test reason for points",
                "signals": {"trend": 0.8, "matchup": 0.6},
            },
            {
                "leg_number": 2,
                "player_name": "Jayson Tatum",
                "player_id": 1628369,
                "team": "BOS",
                "position": "SF",
                "stat_type": "rebounds",
                "line": 7.5,
                "direction": "over",
                "odds": -115,
                "edge_pct": 3.8,
                "confidence": 0.65,
                "model_probability": 0.52,
                "market_probability": 0.535,
                "primary_reason": "Test reason for rebounds",
                "signals": {"trend": 0.7, "usage": 0.5},
            },
            {
                "leg_number": 3,
                "player_name": "Anthony Davis",
                "player_id": 203076,
                "team": "LAL",
                "position": "C",
                "stat_type": "blocks",
                "line": 1.5,
                "direction": "over",
                "odds": +100,
                "edge_pct": 4.1,
                "confidence": 0.68,
                "model_probability": 0.54,
                "market_probability": 0.50,
                "primary_reason": "Test reason for blocks",
                "signals": {"matchup": 0.9},
            },
        ],
    }

    try:
        saved = db.save_parlay(test_parlay)
        parlay_id = saved.get("id")
        print(f"[PASS] Parlay created with ID: {parlay_id[:8]}...")
    except Exception as e:
        print(f"[FAIL] Failed to create parlay: {e}")
        return

    # Read back parlay
    print("\n--- Testing Parlay Retrieval ---")
    try:
        parlays = db.get_parlays_by_date(date.today())
        test_parlays = [p for p in parlays if p["game_id"] == test_game_id]
        if test_parlays:
            p = test_parlays[0]
            print(f"[PASS] Retrieved parlay: {p['parlay_type']}")
            print(f"       Game: {p['away_team']} @ {p['home_team']}")
            print(f"       Legs: {len(p.get('nba_sgp_legs', []))}")
            for leg in p.get('nba_sgp_legs', []):
                print(f"         - {leg['player_name']}: {leg['stat_type']} {leg['direction']} {leg['line']}")
        else:
            print("[FAIL] Could not retrieve test parlay")
            return
    except Exception as e:
        print(f"[FAIL] Failed to retrieve parlay: {e}")
        return

    # Test leg update
    print("\n--- Testing Leg Settlement ---")
    try:
        legs = test_parlays[0].get('nba_sgp_legs', [])
        if legs:
            first_leg = legs[0]
            db.update_leg_result(first_leg['id'], 28.0, 'WIN')
            print(f"[PASS] Updated leg result: {first_leg['player_name']} -> WIN (28.0)")
    except Exception as e:
        print(f"[FAIL] Failed to update leg: {e}")

    # Test parlay settlement
    print("\n--- Testing Parlay Settlement ---")
    try:
        settlement = db.settle_parlay(
            parlay_id=parlay_id,
            legs_hit=2,
            total_legs=3,
            result="LOSS",
            profit=-100.0,
            notes="Test settlement - 2/3 legs hit"
        )
        print(f"[PASS] Settlement created: {settlement['result']} ({settlement['legs_hit']}/{settlement['total_legs']})")
    except Exception as e:
        print(f"[FAIL] Failed to create settlement: {e}")

    # Test unsettled parlays query
    print("\n--- Testing Unsettled Parlays Query ---")
    try:
        unsettled = db.get_unsettled_parlays(game_date=date.today())
        # Our test parlay should NOT be in unsettled (we just settled it)
        test_unsettled = [p for p in unsettled if p["game_id"] == test_game_id]
        if not test_unsettled:
            print("[PASS] Settled parlay correctly excluded from unsettled query")
        else:
            print("[WARN] Settled parlay still appears in unsettled query")
    except Exception as e:
        print(f"[FAIL] Failed to query unsettled parlays: {e}")

    # Clean up test data
    print("\n--- Cleaning Up Test Data ---")
    try:
        # Delete test parlay (cascade deletes legs and settlement)
        db.client.table("nba_sgp_settlements").delete().eq("parlay_id", parlay_id).execute()
        db.client.table("nba_sgp_legs").delete().eq("parlay_id", parlay_id).execute()
        db.client.table("nba_sgp_parlays").delete().eq("id", parlay_id).execute()
        print(f"[PASS] Cleaned up test parlay {parlay_id[:8]}...")
    except Exception as e:
        print(f"[WARN] Failed to clean up test data: {e}")

    # Performance summary (will be empty or show other data)
    print("\n--- Performance Summary ---")
    try:
        summary = db.get_performance_summary(season=2026)
        print(f"Total parlays: {summary['total_parlays']}")
        print(f"Parlay win rate: {summary['parlay_win_rate']:.1%}")
        print(f"Leg hit rate: {summary['leg_hit_rate']:.1%}")
    except Exception as e:
        print(f"[INFO] Performance summary: {e}")

    print("\n" + "=" * 60)
    print("Database Manager Test Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
