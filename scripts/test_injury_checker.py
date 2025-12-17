#!/usr/bin/env python3
"""
Test the NBA Injury Checker with live ESPN data.

Run: python scripts/test_injury_checker.py
"""

import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.injury_checker import get_injury_checker, InjuryStatus

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def main():
    print("=" * 60)
    print("NBA Injury Checker Test")
    print("=" * 60)

    checker = get_injury_checker()

    # Force refresh to get latest data
    print("\nFetching injury data from ESPN...")
    success = checker.refresh()

    if not success:
        print("ERROR: Failed to fetch injury data")
        return

    # Get summary
    summary = checker.get_injury_summary()
    print(f"\n--- Injury Summary ---")
    print(f"Total injuries: {summary['total']}")
    print(f"Last updated: {summary['last_updated']}")
    print(f"\nBy status:")
    for status, count in summary['by_status'].items():
        print(f"  {status}: {count}")

    # Show all OUT players
    print("\n--- All OUT Players ---")
    out_players = checker.get_players_by_status(InjuryStatus.OUT)
    for p in out_players[:15]:  # Show first 15
        return_info = f" (return: {p.return_date})" if p.return_date else ""
        injury_info = f" [{p.injury_type}]" if p.injury_type else ""
        print(f"  {p.player_name} ({p.team}){injury_info}{return_info}")
    if len(out_players) > 15:
        print(f"  ... and {len(out_players) - 15} more")

    # Show Day-to-Day players
    print("\n--- Day-to-Day Players (GTD) ---")
    dtd_players = checker.get_players_by_status(InjuryStatus.DAY_TO_DAY)
    for p in dtd_players[:10]:
        injury_info = f" [{p.injury_type}]" if p.injury_type else ""
        print(f"  {p.player_name} ({p.team}){injury_info}")
    if len(dtd_players) > 10:
        print(f"  ... and {len(dtd_players) - 10} more")

    # Test specific player lookups
    print("\n--- Player Status Lookups ---")
    test_players = [
        ("LeBron James", "LAL"),
        ("Stephen Curry", "GSW"),
        ("Kevin Durant", "PHX"),
        ("Kristaps Porzingis", "ATL"),
        ("Luka Doncic", "DAL"),
        ("Giannis Antetokounmpo", "MIL"),
        ("Jayson Tatum", "BOS"),
        ("NonExistent Player", "UNK"),  # Test non-existent player
    ]

    for player_name, team in test_players:
        status = checker.get_player_status(player_name, team)
        print(f"\n{player_name} ({team}):")
        print(f"  Status: {status.status.value}")
        print(f"  Available: {status.is_available}")
        print(f"  Confirmed Out: {status.is_confirmed_out}")
        print(f"  Confidence Modifier: {status.confidence_modifier}")
        if status.short_comment:
            print(f"  Note: {status.short_comment[:80]}...")

    # Test team injuries
    print("\n--- Team Injuries Example (LAL) ---")
    lal_injuries = checker.get_team_injuries("LAL")
    if lal_injuries:
        for p in lal_injuries:
            print(f"  {p.player_name}: {p.status.value}")
    else:
        print("  No injuries reported")

    # Test is_player_available quick check
    print("\n--- Quick Availability Checks ---")
    for player_name, team in test_players[:5]:
        available = checker.is_player_available(player_name, team)
        out = checker.is_player_out(player_name, team)
        print(f"  {player_name}: available={available}, out={out}")

    print("\n" + "=" * 60)
    print("Test complete!")


if __name__ == "__main__":
    main()
