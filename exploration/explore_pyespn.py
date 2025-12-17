#!/usr/bin/env python3
"""
Explore ESPN API directly for NBA injury data.

Run: python exploration/explore_pyespn.py
"""

import json
import requests
from datetime import datetime


def explore_espn_injuries_detailed():
    """Deep dive into ESPN injuries endpoint structure."""
    print("=" * 60)
    print("ESPN NBA Injuries API - Detailed Exploration")
    print("=" * 60)

    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error fetching injuries: {e}")
        return

    print(f"\nTop-level keys: {list(data.keys())}")
    print(f"Timestamp: {data.get('timestamp')}")
    print(f"Season: {data.get('season', {}).get('year')}")
    print(f"Teams with injuries: {len(data.get('injuries', []))}")

    # Analyze injury structure
    all_injuries = []
    status_counts = {}

    for team_data in data.get('injuries', []):
        team_name = team_data.get('displayName', 'Unknown')
        team_id = team_data.get('id')

        for injury in team_data.get('injuries', []):
            player_id = injury.get('id')
            status = injury.get('status', 'Unknown')
            injury_type = injury.get('type', {})

            # Count statuses
            status_counts[status] = status_counts.get(status, 0) + 1

            # Get athlete details
            athlete = injury.get('athlete', {})
            player_name = athlete.get('displayName', 'Unknown')

            all_injuries.append({
                'player_id': player_id,
                'player_name': player_name,
                'team': team_name,
                'team_id': team_id,
                'status': status,
                'injury_type': injury_type.get('description', ''),
                'injury_detail': injury.get('details', {}).get('detail', ''),
                'long_comment': injury.get('longComment', '')[:100] + '...' if injury.get('longComment') else '',
            })

    print(f"\nTotal injured players: {len(all_injuries)}")
    print(f"\nStatus breakdown:")
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {status}: {count}")

    # Show sample injuries for each status type
    print("\n" + "-" * 60)
    print("Sample injuries by status:")
    print("-" * 60)

    shown_statuses = set()
    for inj in all_injuries:
        if inj['status'] not in shown_statuses:
            shown_statuses.add(inj['status'])
            print(f"\n[{inj['status']}] {inj['player_name']} ({inj['team']})")
            print(f"  Injury: {inj['injury_type']} - {inj['injury_detail']}")
            if inj['long_comment']:
                print(f"  Notes: {inj['long_comment']}")

    # Show full structure of one injury
    print("\n" + "-" * 60)
    print("Full injury object structure (first entry):")
    print("-" * 60)

    if data.get('injuries') and data['injuries'][0].get('injuries'):
        sample = data['injuries'][0]['injuries'][0]
        print(json.dumps(sample, indent=2))


def explore_espn_api_direct():
    """Try hitting ESPN API directly for injury data."""

    print("\n" + "=" * 60)
    print("Exploring ESPN API directly")
    print("=" * 60)

    # ESPN's public API endpoints
    endpoints = [
        # Injuries endpoint
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
        # Teams with roster
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams",
        # Scoreboard (has injury info sometimes)
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    ]

    for url in endpoints:
        print(f"\n--- Fetching: {url.split('/')[-1]} ---")
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # Pretty print structure
            if 'injuries' in url:
                print(f"Keys: {list(data.keys())}")
                if 'injuries' in data:
                    print(f"Injuries count: {len(data.get('injuries', []))}")
                    if data.get('injuries'):
                        print(f"Sample injury: {json.dumps(data['injuries'][0], indent=2)[:500]}")
            elif 'teams' in url:
                teams = data.get('sports', [{}])[0].get('leagues', [{}])[0].get('teams', [])
                print(f"Teams count: {len(teams)}")
            elif 'scoreboard' in url:
                events = data.get('events', [])
                print(f"Events today: {len(events)}")

        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    explore_espn_injuries_detailed()
