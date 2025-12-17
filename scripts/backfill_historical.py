#!/usr/bin/env python3
"""
Historical Backfill Script for NBA SGP Engine

Fetches historical odds from Odds API, generates parlays using our edge calculator,
and settles them against actual box scores from nba_api.

This enables:
1. Backtesting our algorithm on historical data
2. Analyzing hit rates by signal, stat type, edge threshold
3. Identifying optimization opportunities

Usage:
    # Backfill a single date
    python scripts/backfill_historical.py --date 2025-12-10

    # Backfill a date range
    python scripts/backfill_historical.py --start 2025-11-11 --end 2025-12-16

    # Backfill and settle
    python scripts/backfill_historical.py --date 2025-12-10 --settle

    # Dry run (no database writes)
    python scripts/backfill_historical.py --date 2025-12-10 --dry-run
"""

import os
import sys
import argparse
import logging
import json
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from zoneinfo import ZoneInfo

import requests
import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
for env_path in ['.env.local', '.env']:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('backfill')

ET = ZoneInfo('America/New_York')


# =============================================================================
# HISTORICAL ODDS CLIENT
# =============================================================================

class HistoricalOddsClient:
    """Client for fetching historical odds from The Odds API."""

    BASE_URL = "https://api.the-odds-api.com/v4"
    SPORT = "basketball_nba"

    # Player prop markets to fetch
    PROP_MARKETS = [
        'player_points',
        'player_rebounds',
        'player_assists',
        'player_threes',
        'player_blocks',
        'player_steals',
        'player_turnovers',
        'player_points_rebounds_assists',
    ]

    # Team abbreviation mapping
    TEAM_ABBREV = {
        'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN',
        'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE',
        'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET',
        'Golden State Warriors': 'GSW', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
        'Los Angeles Clippers': 'LAC', 'Los Angeles Lakers': 'LAL', 'Memphis Grizzlies': 'MEM',
        'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN',
        'New Orleans Pelicans': 'NOP', 'New York Knicks': 'NYK', 'Oklahoma City Thunder': 'OKC',
        'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX',
        'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC', 'San Antonio Spurs': 'SAS',
        'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA', 'Washington Wizards': 'WAS',
    }

    MARKET_TO_STAT = {
        'player_points': 'points',
        'player_rebounds': 'rebounds',
        'player_assists': 'assists',
        'player_threes': 'threes',
        'player_blocks': 'blocks',
        'player_steals': 'steals',
        'player_turnovers': 'turnovers',
        'player_points_rebounds_assists': 'pra',
    }

    def __init__(self):
        self.api_key = os.environ.get('ODDS_API_KEY')
        if not self.api_key:
            raise ValueError("ODDS_API_KEY not set")
        self.requests_remaining = None

    def _request(self, url: str, params: Dict) -> Optional[Dict]:
        """Make API request with rate limiting."""
        params['apiKey'] = self.api_key
        time.sleep(0.5)  # Rate limit

        try:
            response = requests.get(url, params=params)
            self.requests_remaining = response.headers.get('x-requests-remaining')
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"API error: {e}")
            return None

    def get_historical_events(self, target_date: date) -> List[Dict]:
        """Get NBA events for a historical date."""
        url = f"{self.BASE_URL}/historical/sports/{self.SPORT}/events"
        params = {'date': f'{target_date}T12:00:00Z'}

        data = self._request(url, params)
        if not data:
            return []

        events = data.get('data', [])
        logger.info(f"Found {len(events)} events for {target_date}")
        return events

    def get_historical_odds(self, event_id: str, target_date: date) -> Optional[Dict]:
        """Get historical odds (including props) for an event."""
        url = f"{self.BASE_URL}/historical/sports/{self.SPORT}/events/{event_id}/odds"

        # Request odds from before game time (noon ET on game day)
        params = {
            'date': f'{target_date}T16:00:00Z',  # Noon ET = 16:00 UTC
            'regions': 'us',
            'markets': ','.join(['spreads', 'totals'] + self.PROP_MARKETS),
            'oddsFormat': 'american',
        }

        data = self._request(url, params)
        if not data:
            return None

        return data.get('data', {})

    def parse_game_and_props(self, odds_data: Dict) -> Dict:
        """Parse odds data into game info and props."""
        result = {
            'game_id': odds_data.get('id', ''),
            'home_team': self.TEAM_ABBREV.get(odds_data.get('home_team', ''), 'UNK'),
            'away_team': self.TEAM_ABBREV.get(odds_data.get('away_team', ''), 'UNK'),
            'home_team_full': odds_data.get('home_team', ''),
            'away_team_full': odds_data.get('away_team', ''),
            'commence_time': odds_data.get('commence_time', ''),
            'spread': None,
            'total': None,
            'props': [],
        }

        for bookmaker in odds_data.get('bookmakers', []):
            bk_name = bookmaker.get('key', '')

            for market in bookmaker.get('markets', []):
                market_key = market.get('key', '')
                outcomes = market.get('outcomes', [])

                # Parse spread
                if market_key == 'spreads' and result['spread'] is None:
                    for o in outcomes:
                        if o.get('name') == odds_data.get('home_team'):
                            result['spread'] = o.get('point', 0)
                            break

                # Parse total
                elif market_key == 'totals' and result['total'] is None:
                    for o in outcomes:
                        if o.get('name') == 'Over':
                            result['total'] = o.get('point', 220)
                            break

                # Parse player props
                elif market_key in self.MARKET_TO_STAT:
                    stat_type = self.MARKET_TO_STAT[market_key]

                    # Group by player + line
                    props_by_key = {}
                    for o in outcomes:
                        player = o.get('description', '')
                        line = o.get('point', 0)
                        key = (player, line)

                        if key not in props_by_key:
                            props_by_key[key] = {'over': None, 'under': None}

                        if o.get('name') == 'Over':
                            props_by_key[key]['over'] = o.get('price', -110)
                        elif o.get('name') == 'Under':
                            props_by_key[key]['under'] = o.get('price', -110)

                    # Create prop entries
                    for (player, line), odds in props_by_key.items():
                        if odds['over'] and odds['under']:
                            result['props'].append({
                                'player_name': player,
                                'stat_type': stat_type,
                                'line': line,
                                'over_odds': odds['over'],
                                'under_odds': odds['under'],
                                'bookmaker': bk_name,
                            })

        return result


# =============================================================================
# BACKFILL ENGINE
# =============================================================================

class BackfillEngine:
    """Engine for backfilling historical SGP data."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.historical_client = HistoricalOddsClient()

        # Lazy-loaded components
        self._db = None
        self._context_builder = None
        self._edge_calculator = None
        self._data_provider = None

        # Stats tracking
        self.stats = {
            'dates_processed': 0,
            'games_processed': 0,
            'parlays_generated': 0,
            'legs_generated': 0,
            'api_calls': 0,
        }

    @property
    def db(self):
        if self._db is None:
            from src.db_manager import get_db_manager
            self._db = get_db_manager()
        return self._db

    @property
    def context_builder(self):
        if self._context_builder is None:
            from src.context_builder import get_context_builder
            self._context_builder = get_context_builder()
        return self._context_builder

    @property
    def edge_calculator(self):
        if self._edge_calculator is None:
            from src.edge_calculator import get_edge_calculator
            self._edge_calculator = get_edge_calculator()
        return self._edge_calculator

    @property
    def data_provider(self):
        if self._data_provider is None:
            from src.data_provider import get_data_provider
            self._data_provider = get_data_provider()
        return self._data_provider

    def backfill_date(self, target_date: date) -> Dict[str, Any]:
        """Backfill all games for a single date."""
        logger.info(f"Backfilling {target_date}")

        result = {
            'date': str(target_date),
            'games_found': 0,
            'parlays_generated': 0,
            'legs_generated': 0,
            'errors': [],
        }

        # Get historical events
        events = self.historical_client.get_historical_events(target_date)
        self.stats['api_calls'] += 1
        result['games_found'] = len(events)

        if not events:
            logger.warning(f"No events found for {target_date}")
            return result

        # Process each game
        for event in events:
            try:
                parlay = self._process_game(event, target_date)
                if parlay:
                    result['parlays_generated'] += 1
                    result['legs_generated'] += parlay.get('total_legs', 0)
            except Exception as e:
                logger.error(f"Error processing {event.get('id')}: {e}")
                result['errors'].append(str(e))

        self.stats['dates_processed'] += 1
        self.stats['games_processed'] += len(events)
        self.stats['parlays_generated'] += result['parlays_generated']
        self.stats['legs_generated'] += result['legs_generated']

        return result

    def _process_game(self, event: Dict, target_date: date) -> Optional[Dict]:
        """Process a single game and generate parlay."""
        event_id = event['id']
        home_team = self.historical_client.TEAM_ABBREV.get(event.get('home_team', ''), 'UNK')
        away_team = self.historical_client.TEAM_ABBREV.get(event.get('away_team', ''), 'UNK')

        logger.info(f"  Processing: {away_team} @ {home_team}")

        # Get historical odds
        odds_data = self.historical_client.get_historical_odds(event_id, target_date)
        self.stats['api_calls'] += 1

        if not odds_data:
            logger.warning(f"  No odds data for {event_id}")
            return None

        # Parse game and props
        game_data = self.historical_client.parse_game_and_props(odds_data)
        props = game_data['props']

        logger.info(f"    Found {len(props)} props")

        if len(props) < 3:
            logger.warning(f"    Not enough props")
            return None

        # Build game context for context builder
        game = {
            'id': game_data['game_id'],
            'home_team': game_data['home_team'],
            'away_team': game_data['away_team'],
            'total': game_data['total'] or 220,
            'spread': game_data['spread'] or 0,
        }

        # Calculate edges for each prop
        edges = []
        for prop in props:
            try:
                # Build context
                context = self.context_builder.build_context(
                    player_name=prop['player_name'],
                    stat_type=prop['stat_type'],
                    line=prop['line'],
                    over_odds=prop['over_odds'],
                    under_odds=prop['under_odds'],
                    game=game,
                    game_date=str(target_date),
                )

                if not context:
                    continue

                # Calculate edge
                edge_result = self.edge_calculator.calculate_edge(context)
                if edge_result and abs(edge_result.edge_score) >= 0.08:
                    edges.append({
                        'prop': prop,
                        'edge': edge_result,
                        'context': context,
                    })
            except Exception as e:
                logger.debug(f"    Edge error for {prop['player_name']}: {e}")

        logger.info(f"    Props with edge: {len(edges)}")

        if len(edges) < 3:
            return None

        # Sort by edge and select top 3 from DIFFERENT players
        edges.sort(key=lambda x: abs(x['edge'].edge_score), reverse=True)

        # Ensure unique players in parlay
        top_edges = []
        seen_players = set()
        for edge in edges:
            player_name = edge['prop']['player_name']
            if player_name not in seen_players:
                top_edges.append(edge)
                seen_players.add(player_name)
                if len(top_edges) >= 3:
                    break

        if len(top_edges) < 3:
            logger.warning(f"    Not enough unique players for parlay")
            return None

        # Build legs
        legs = []
        combined_implied_prob = 1.0

        for i, e in enumerate(top_edges, 1):
            prop = e['prop']
            edge = e['edge']
            ctx = e['context']

            direction = edge.direction
            odds = prop['over_odds'] if direction == 'over' else prop['under_odds']

            # Calculate implied probability
            if odds >= 0:
                implied_prob = 100 / (odds + 100)
            else:
                implied_prob = abs(odds) / (abs(odds) + 100)

            leg = {
                'leg_number': i,
                'player_name': prop['player_name'],
                'player_id': ctx.player_id if ctx else None,
                'team': ctx.team if ctx else '',
                'stat_type': prop['stat_type'],
                'line': prop['line'],
                'direction': direction,
                'odds': odds,
                'edge_pct': edge.edge_score * 100,
                'confidence': edge.confidence,
                'model_probability': 0.5 + edge.edge_score / 2,
                'market_probability': implied_prob,
                'primary_reason': edge.recommendation,
                'supporting_reasons': [s.evidence for s in edge.signals if s.strength != 0][:3],
                'signals': {s.signal_type: round(s.strength, 3) for s in edge.signals},
                'pipeline_score': round(edge.edge_score * 100, 2),
                'pipeline_rank': i,
            }
            legs.append(leg)
            combined_implied_prob *= implied_prob

        # Calculate combined odds
        if 0 < combined_implied_prob < 1:
            if combined_implied_prob >= 0.5:
                combined_odds = int(-100 * combined_implied_prob / (1 - combined_implied_prob))
            else:
                combined_odds = int(100 * (1 - combined_implied_prob) / combined_implied_prob)
        else:
            combined_odds = 100

        # Parse actual game date from commence_time (UTC → ET)
        commence_time = game_data.get('commence_time', '')
        if commence_time:
            try:
                # Parse ISO format and convert to ET
                from datetime import datetime
                utc_time = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                et_time = utc_time.astimezone(ET)
                actual_game_date = et_time.date()
            except Exception:
                actual_game_date = target_date
        else:
            actual_game_date = target_date

        # Determine season and type based on actual game date
        if actual_game_date >= date(2025, 11, 11):
            season = 2026
            season_type = 'cup' if actual_game_date <= date(2025, 12, 17) else 'regular'
        elif actual_game_date >= date(2024, 10, 22):
            season = 2025  # 2024-25 season
            season_type = 'cup' if date(2024, 11, 12) <= actual_game_date <= date(2024, 12, 17) else 'regular'
        else:
            season = 2025
            season_type = 'regular'

        # Build parlay
        parlay = {
            'id': str(uuid.uuid4()),
            'parlay_type': 'primary',
            'game_id': game_data['game_id'],
            'game_date': str(actual_game_date),
            'home_team': game_data['home_team'],
            'away_team': game_data['away_team'],
            'game_slot': 'EVENING',
            'total_legs': len(legs),
            'combined_odds': combined_odds,
            'implied_probability': combined_implied_prob,
            'thesis': f"Historical backfill for {away_team}@{home_team} on {actual_game_date}",
            'season': season,
            'season_type': season_type,
            'legs': legs,
        }

        # Save to database
        if not self.dry_run:
            try:
                self.db.save_parlay(parlay)
                logger.info(f"    Saved parlay: {len(legs)} legs, +{combined_odds}")
            except Exception as e:
                logger.error(f"    Failed to save: {e}")
                return None
        else:
            logger.info(f"    [DRY RUN] Would save parlay: {len(legs)} legs")

        return parlay

    def settle_date(self, target_date: date) -> Dict[str, Any]:
        """Settle all parlays for a date."""
        from src.settlement import SettlementEngine

        settlement_engine = SettlementEngine(self.db)
        result = settlement_engine.settle_date(target_date)

        return result

    def backfill_range(self, start_date: date, end_date: date) -> Dict[str, Any]:
        """Backfill a range of dates."""
        results = []
        current = start_date

        while current <= end_date:
            result = self.backfill_date(current)
            results.append(result)
            current += timedelta(days=1)

        return {
            'start_date': str(start_date),
            'end_date': str(end_date),
            'dates': results,
            'totals': self.stats,
            'api_remaining': self.historical_client.requests_remaining,
        }


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Historical Backfill for NBA SGP')
    parser.add_argument('--date', type=str, help='Single date to backfill (YYYY-MM-DD)')
    parser.add_argument('--start', type=str, help='Start date for range (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date for range (YYYY-MM-DD)')
    parser.add_argument('--settle', action='store_true', help='Settle after backfill')
    parser.add_argument('--settle-only', action='store_true', help='Only settle, no backfill')
    parser.add_argument('--clear', action='store_true', help='Clear existing settlements before settling')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no DB writes)')

    args = parser.parse_args()

    engine = BackfillEngine(dry_run=args.dry_run)

    # Determine dates to process
    if args.date:
        dates = [datetime.strptime(args.date, '%Y-%m-%d').date()]
    elif args.start and args.end:
        start = datetime.strptime(args.start, '%Y-%m-%d').date()
        end = datetime.strptime(args.end, '%Y-%m-%d').date()
        dates = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
    else:
        print("Error: Specify --date or --start/--end")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("NBA SGP HISTORICAL BACKFILL")
    print("=" * 70)
    print(f"Dates to process: {len(dates)}")
    print(f"Dry run: {args.dry_run}")
    print(f"Settle: {args.settle}")
    print("=" * 70 + "\n")

    # Backfill
    if not args.settle_only:
        for target_date in dates:
            result = engine.backfill_date(target_date)
            print(f"{target_date}: {result['parlays_generated']} parlays, {result['legs_generated']} legs")

    # Clear settlements if requested
    if args.clear and (args.settle or args.settle_only):
        print("\n" + "-" * 70)
        print("CLEARING SETTLEMENTS")
        print("-" * 70)
        from src.db_manager import get_db_manager
        db = get_db_manager()
        for target_date in dates:
            cleared = db.clear_settlements_for_date(target_date)
            print(f"{target_date}: Cleared {cleared} settlements")

    # Settle
    if args.settle or args.settle_only:
        print("\n" + "-" * 70)
        print("SETTLEMENT")
        print("-" * 70)
        for target_date in dates:
            result = engine.settle_date(target_date)
            print(f"{target_date}: {result.get('wins', 0)}W / {result.get('losses', 0)}L / {result.get('voids', 0)}V")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Dates processed: {engine.stats['dates_processed']}")
    print(f"Games processed: {engine.stats['games_processed']}")
    print(f"Parlays generated: {engine.stats['parlays_generated']}")
    print(f"Legs generated: {engine.stats['legs_generated']}")
    print(f"API calls made: {engine.stats['api_calls']}")
    print(f"API credits remaining: {engine.historical_client.requests_remaining}")
    print("=" * 70)


if __name__ == '__main__':
    main()
