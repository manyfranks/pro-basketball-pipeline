#!/usr/bin/env python3
"""
NBA Daily Pipeline Orchestrator

Runs the daily NBA SGP workflow:
1. Settlement - Settle yesterday's parlays against actual box scores
2. SGP Generation - Generate parlays for today's games

CRITICAL: All dates are in Eastern Time (ET). The NBA operates on ET.

Usage:
    # Run full pipeline for today
    python -m scripts.nba_daily_orchestrator

    # Run for specific date (in ET)
    python -m scripts.nba_daily_orchestrator --date 2025-12-16

    # Settlement only (morning run)
    python -m scripts.nba_daily_orchestrator --settle-only

    # SGP generation only (afternoon run after injury reports)
    python -m scripts.nba_daily_orchestrator --generate-only

    # Force refresh (overwrite existing predictions)
    python -m scripts.nba_daily_orchestrator --generate-only --force-refresh

    # Dry run (don't write to database)
    python -m scripts.nba_daily_orchestrator --dry-run

Daily Schedule (configured in Railway):
    - 15:00 UTC (10am ET / 7am PT): Settlement + Early SGP
    - 19:00 UTC (2pm ET / 11am PT): Final SGP after injury cutoff
"""

import os
import sys
import argparse
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
for env_path in ['.env.local', '.env', '../.env.local', '../.env']:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('nba_orchestrator')


# =============================================================================
# TIMEZONE HANDLING (CRITICAL)
# =============================================================================
# NBA operates on Eastern Time. All dates should be ET.
# Schedulers run in UTC. This section handles the conversion.

ET = ZoneInfo('America/New_York')
UTC = ZoneInfo('UTC')


def get_now_et() -> datetime:
    """Get current datetime in Eastern Time."""
    return datetime.now(ET)


def get_today_et() -> date:
    """Get today's date in Eastern Time."""
    return datetime.now(ET).date()


def get_yesterday_et() -> date:
    """Get yesterday's date in Eastern Time (for settlement)."""
    return (datetime.now(ET) - timedelta(days=1)).date()


def parse_date_et(date_str: str) -> date:
    """Parse a date string, treating it as ET."""
    return datetime.strptime(date_str, '%Y-%m-%d').date()


# =============================================================================
# SEASON CONFIGURATION
# =============================================================================

SEASON_CONFIG = {
    2026: {  # 2025-26 Season (use ending year as key)
        'preseason_start': date(2025, 10, 3),
        'regular_season_start': date(2025, 10, 21),
        'nba_cup_start': date(2025, 11, 11),
        'nba_cup_knockout': date(2025, 12, 9),
        'nba_cup_finals': date(2025, 12, 16),
        'christmas': date(2025, 12, 25),
        'allstar_start': date(2026, 2, 13),
        'allstar_end': date(2026, 2, 18),
        'regular_season_end': date(2026, 4, 12),
        'playin_start': date(2026, 4, 14),
        'playin_end': date(2026, 4, 17),
        'playoffs_start': date(2026, 4, 18),
        'finals_end': date(2026, 6, 21),
    }
}


def get_season_info(target_date: date) -> Dict[str, Any]:
    """
    Determine season year and phase for a given date.

    Returns:
        dict with 'season' (int) and 'season_type' (str)
    """
    # Determine season year (NBA season spans two calendar years)
    # Season 2025-26 runs Oct 2025 - June 2026
    if target_date.month >= 10:
        season = target_date.year + 1  # Oct-Dec: next year's season
    else:
        season = target_date.year  # Jan-Sep: current year's season

    config = SEASON_CONFIG.get(season)
    if not config:
        # Default to regular season if not configured
        return {'season': season, 'season_type': 'regular', 'should_run': True}

    # Check season phase
    if target_date < config['preseason_start']:
        return {'season': season - 1, 'season_type': 'offseason', 'should_run': False}

    if target_date < config['regular_season_start']:
        return {'season': season, 'season_type': 'preseason', 'should_run': False}

    if config['allstar_start'] <= target_date <= config['allstar_end']:
        return {'season': season, 'season_type': 'allstar_break', 'should_run': False}

    if config['playin_start'] <= target_date <= config['playin_end']:
        return {'season': season, 'season_type': 'playin', 'should_run': True}

    if target_date >= config['playoffs_start']:
        if target_date > config['finals_end']:
            return {'season': season, 'season_type': 'offseason', 'should_run': False}
        return {'season': season, 'season_type': 'playoffs', 'should_run': True}

    # NBA Cup check (during regular season)
    is_cup_game = config['nba_cup_start'] <= target_date <= config['nba_cup_finals']

    return {
        'season': season,
        'season_type': 'cup' if is_cup_game else 'regular',
        'should_run': True,
        'is_cup_period': is_cup_game,
    }


# =============================================================================
# GAME SLOT CLASSIFICATION
# =============================================================================

def classify_game_slot(game_time_et: datetime) -> str:
    """
    Classify a game into a slot based on ET start time.

    Returns: 'AFTERNOON', 'EVENING', or 'LATE'
    """
    hour = game_time_et.hour

    if hour < 17:  # Before 5pm ET
        return 'AFTERNOON'
    elif hour < 21:  # 5pm - 9pm ET
        return 'EVENING'
    else:  # 9pm+ ET
        return 'LATE'


# =============================================================================
# ORCHESTRATOR CLASS
# =============================================================================

class NBADailyOrchestrator:
    """
    Orchestrates the NBA SGP daily pipeline.

    Pipeline Stages:
    1. Settlement - Settle yesterday's parlays
    2. SGP Generation - Generate today's parlays

    The pipeline is designed for two daily runs:
    - Morning (7am PT): Settlement + Early SGP
    - Afternoon (2pm ET): Final SGP with updated injury info
    """

    def __init__(
        self,
        dry_run: bool = False,
        force_refresh: bool = False,
    ):
        """
        Initialize orchestrator.

        Args:
            dry_run: If True, don't write to database
            force_refresh: If True, overwrite existing predictions
        """
        self.dry_run = dry_run
        self.force_refresh = force_refresh
        self.results = {
            'settlement': None,
            'sgp': None,
            'errors': [],
        }

        # Initialize components (lazy load to handle import errors)
        self._db = None
        self._odds_client = None
        self._data_provider = None
        self._injury_checker = None
        self._edge_calculator = None
        self._settlement_engine = None
        self._thesis_generator = None
        self._context_builder = None

    @property
    def db(self):
        """Lazy load database manager."""
        if self._db is None:
            from src.db_manager import get_db_manager
            self._db = get_db_manager()
        return self._db

    @property
    def odds_client(self):
        """Lazy load odds client."""
        if self._odds_client is None:
            from src.odds_client import get_odds_client
            self._odds_client = get_odds_client()
        return self._odds_client

    @property
    def injury_checker(self):
        """Lazy load injury checker."""
        if self._injury_checker is None:
            from src.injury_checker import get_injury_checker
            self._injury_checker = get_injury_checker()
        return self._injury_checker

    @property
    def data_provider(self):
        """Lazy load data provider."""
        if self._data_provider is None:
            from src.data_provider import get_data_provider
            self._data_provider = get_data_provider()
        return self._data_provider

    @property
    def edge_calculator(self):
        """Lazy load edge calculator."""
        if self._edge_calculator is None:
            from src.edge_calculator import get_edge_calculator
            self._edge_calculator = get_edge_calculator()
        return self._edge_calculator

    @property
    def settlement_engine(self):
        """Lazy load settlement engine."""
        if self._settlement_engine is None:
            from src.settlement import SettlementEngine
            self._settlement_engine = SettlementEngine(self.db)
        return self._settlement_engine

    @property
    def thesis_generator(self):
        """Lazy load thesis generator."""
        if self._thesis_generator is None:
            from src.thesis_generator import get_thesis_generator
            self._thesis_generator = get_thesis_generator()
        return self._thesis_generator

    @property
    def context_builder(self):
        """Lazy load context builder."""
        if self._context_builder is None:
            from src.context_builder import get_context_builder
            self._context_builder = get_context_builder()
        return self._context_builder

    def run(
        self,
        target_date: Optional[date] = None,
        settle_only: bool = False,
        generate_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Run the daily pipeline.

        Args:
            target_date: Date to process (in ET). Defaults to today.
            settle_only: Only run settlement stage
            generate_only: Only run SGP generation stage

        Returns:
            Results dictionary
        """
        if target_date is None:
            target_date = get_today_et()

        yesterday = target_date - timedelta(days=1)
        season_info = get_season_info(target_date)
        now_et = get_now_et()

        # Print header
        print("\n" + "=" * 80)
        print("NBA SGP DAILY ORCHESTRATOR")
        print("=" * 80)
        print(f"Current Time: {now_et.strftime('%Y-%m-%d %H:%M:%S')} ET")
        print(f"Target Date: {target_date} (ET)")
        print(f"Settlement Date: {yesterday}")
        print(f"Season: {season_info['season']} ({season_info['season_type']})")
        print(f"Dry Run: {self.dry_run}")
        print(f"Force Refresh: {self.force_refresh}")
        print("=" * 80)

        # Check if we should run
        if not season_info.get('should_run', True):
            logger.warning(f"Skipping - season_type={season_info['season_type']}")
            print(f"\n[SKIP] No games during {season_info['season_type']}")
            return self.results

        # Stage 1: Settlement (unless generate_only)
        if not generate_only:
            print("\n" + "-" * 80)
            print("STAGE 1: SETTLEMENT (Yesterday's Parlays)")
            print("-" * 80)
            self.results['settlement'] = self._run_settlement(
                yesterday, season_info
            )

        # Stage 2: SGP Generation (unless settle_only)
        if not settle_only:
            print("\n" + "-" * 80)
            print("STAGE 2: SGP GENERATION (Today's Games)")
            print("-" * 80)
            self.results['sgp'] = self._run_sgp_generation(
                target_date, season_info
            )

        # Print summary
        self._print_summary()

        return self.results

    def _run_settlement(
        self,
        settle_date: date,
        season_info: Dict,
    ) -> Dict[str, Any]:
        """
        Settle yesterday's parlays against actual results.

        Args:
            settle_date: Date to settle (yesterday)
            season_info: Season info dict

        Returns:
            Settlement results
        """
        if self.dry_run:
            # In dry run, just check what would be settled
            unsettled = self.db.get_unsettled_parlays(game_date=settle_date)
            print(f"  [DRY RUN] Would settle {len(unsettled)} parlays")
            for p in unsettled[:3]:
                print(f"    - {p['parlay_type']}: {p['away_team']}@{p['home_team']}")
            if len(unsettled) > 3:
                print(f"    ... and {len(unsettled) - 3} more")
            return {
                'date': str(settle_date),
                'parlays_found': len(unsettled),
                'parlays_settled': 0,
                'dry_run': True,
            }

        try:
            # Use settlement engine
            result = self.settlement_engine.settle_date(settle_date)

            print(f"  Parlays found: {result.get('parlays_found', 0)}")
            print(f"  Parlays settled: {result.get('parlays_settled', 0)}")
            print(f"  Results: {result.get('wins', 0)}W / {result.get('losses', 0)}L / {result.get('voids', 0)}V")

            if result.get('errors'):
                for err in result['errors'][:3]:
                    print(f"  [ERROR] {err}")

            return result

        except Exception as e:
            logger.error(f"Settlement error: {e}")
            self.results['errors'].append(f"Settlement: {e}")
            return {
                'date': str(settle_date),
                'parlays_found': 0,
                'parlays_settled': 0,
                'error': str(e),
            }

    def _run_sgp_generation(
        self,
        target_date: date,
        season_info: Dict,
    ) -> Dict[str, Any]:
        """
        Generate SGP parlays for today's games.

        Args:
            target_date: Date to generate for
            season_info: Season info dict

        Returns:
            Generation results
        """
        result = {
            'date': str(target_date),
            'season': season_info['season'],
            'season_type': season_info['season_type'],
            'games_found': 0,
            'parlays_generated': 0,
            'total_legs': 0,
        }

        try:
            # Step 1: Refresh injury data
            logger.info("Refreshing injury data...")
            print("  Refreshing injury data from ESPN...")
            injury_success = self.injury_checker.refresh()
            if injury_success:
                summary = self.injury_checker.get_injury_summary()
                print(f"    {summary['total']} injuries loaded")
            else:
                print("    [WARN] Failed to refresh injuries")

            # Step 2: Fetch today's games from Odds API
            logger.info("Fetching today's games...")
            print("  Fetching games from Odds API...")

            games = self.odds_client.get_todays_games()
            result['games_found'] = len(games)

            if not games:
                print(f"  No games found for {target_date}")
                return result

            print(f"    Found {len(games)} games:")
            for g in games:
                total = g.get('total', 'N/A')
                print(f"      {g['away_team']} @ {g['home_team']} (O/U: {total})")

            # Step 3: Process each game
            for game in games:
                try:
                    parlays = self._process_game(game, target_date, season_info)
                    result['parlays_generated'] += len(parlays)
                    for p in parlays:
                        result['total_legs'] += p.get('total_legs', 0)
                except Exception as e:
                    logger.error(f"Error processing game {game.get('id')}: {e}")
                    self.results['errors'].append(f"Game {game.get('id')}: {e}")

            print(f"\n  Generated {result['parlays_generated']} parlays")
            print(f"  Total legs: {result['total_legs']}")

        except Exception as e:
            logger.error(f"SGP generation error: {e}")
            self.results['errors'].append(f"SGP Generation: {e}")
            result['error'] = str(e)

        return result

    def _process_game(
        self,
        game: Dict,
        target_date: date,
        season_info: Dict,
    ) -> List[Dict]:
        """
        Process a single game and generate SGP parlays.

        Args:
            game: Game data from Odds API
            target_date: Target date
            season_info: Season info

        Returns:
            List of generated parlay dicts
        """
        import uuid
        from datetime import datetime
        from zoneinfo import ZoneInfo

        parlays = []
        game_id = game.get('id')
        home_team = game.get('home_team', '')
        away_team = game.get('away_team', '')
        game_total = game.get('total', 220)
        spread = game.get('spread', 0)

        logger.info(f"Processing game: {away_team} @ {home_team}")
        print(f"\n  Processing: {away_team} @ {home_team}")

        # Step 1: Fetch player props
        props = self.odds_client.get_player_props(game_id)
        if not props:
            logger.warning(f"No props found for {game_id}")
            print(f"    No props available")
            return parlays

        print(f"    Fetched {len(props)} prop lines")

        # Step 2: Filter out injured players
        available_props = []
        for prop in props:
            player_status = self.injury_checker.get_player_status(prop.player_name)
            if player_status.is_available:
                available_props.append(prop)
            elif player_status.is_confirmed_out:
                logger.debug(f"Filtering out injured: {prop.player_name}")

        print(f"    After injury filter: {len(available_props)} props")

        if len(available_props) < 3:
            logger.warning(f"Not enough props after filtering for {game_id}")
            return parlays

        # Step 3: Build enriched contexts and calculate edges
        print("    Enriching props with player data...")
        edges = []
        enriched_count = 0

        for prop in available_props:
            try:
                # Build fully enriched context using context builder
                context = self.context_builder.build_context(
                    player_name=prop.player_name,
                    stat_type=prop.stat_type,
                    line=prop.line,
                    over_odds=prop.over_odds,
                    under_odds=prop.under_odds,
                    game=game,
                    game_date=str(target_date),
                )

                if not context:
                    logger.debug(f"No context for {prop.player_name}")
                    continue

                enriched_count += 1

                # Calculate edge
                edge_result = self.edge_calculator.calculate_edge(context)
                if edge_result and abs(edge_result.edge_score) >= 0.08:
                    edges.append({
                        'prop': prop,
                        'edge': edge_result,
                        'context': context,
                    })
            except Exception as e:
                logger.debug(f"Edge calc error for {prop.player_name}: {e}")

        print(f"    Enriched {enriched_count}/{len(available_props)} props")

        print(f"    Props with edge: {len(edges)}")

        if len(edges) < 3:
            logger.info(f"Not enough edges for {away_team}@{home_team}")
            return parlays

        # Step 4: Sort by edge score and select top legs from DIFFERENT players
        edges.sort(key=lambda x: abs(x['edge'].edge_score), reverse=True)

        # Build a 3-leg parlay from top edges (ensure unique players)
        top_edges = []
        seen_players = set()
        for edge in edges:
            player_name = edge['prop'].player_name
            if player_name not in seen_players:
                top_edges.append(edge)
                seen_players.add(player_name)
                if len(top_edges) >= 3:
                    break

        if len(top_edges) < 3:
            logger.info(f"Not enough unique players for parlay in {away_team}@{home_team}")
            return parlays

        # Create legs list
        legs = []
        combined_implied_prob = 1.0  # For combined odds calculation
        for i, e in enumerate(top_edges, 1):
            prop = e['prop']
            edge = e['edge']
            ctx = e.get('context')

            # Use over or under based on edge direction
            odds = prop.over_odds if edge.direction == 'over' else prop.under_odds
            implied_prob = prop.over_implied_prob if edge.direction == 'over' else prop.under_implied_prob

            leg = {
                'leg_number': i,
                'player_name': prop.player_name,
                'player_id': ctx.player_id if ctx else None,
                'team': ctx.team if ctx else '',
                'position': '',  # Could be enriched from data_provider
                'stat_type': prop.stat_type,
                'line': prop.line,
                'direction': edge.direction,
                'odds': odds,
                'edge_pct': edge.edge_score * 100,
                'confidence': edge.confidence,
                'model_probability': 0.5 + edge.edge_score / 2,
                'market_probability': implied_prob,
                'primary_reason': edge.recommendation,
                'supporting_reasons': [s.evidence for s in edge.signals if s.strength != 0][:3],
                'risk_factors': [s.evidence for s in edge.signals if s.strength * edge.edge_score < 0][:2],
                'signals': {s.signal_type: round(s.strength, 3) for s in edge.signals},
                'pipeline_score': round(edge.edge_score * 100, 2),
                'pipeline_confidence': self._confidence_tier(edge.confidence),
                'pipeline_rank': i,
            }
            legs.append(leg)

            # Multiply implied probabilities for parlay odds
            combined_implied_prob *= implied_prob

        # Convert combined probability to American odds
        if combined_implied_prob > 0 and combined_implied_prob < 1:
            if combined_implied_prob >= 0.5:
                combined_odds = int(-100 * combined_implied_prob / (1 - combined_implied_prob))
            else:
                combined_odds = int(100 * (1 - combined_implied_prob) / combined_implied_prob)
        else:
            combined_odds = 100

        # Calculate game slot
        commence_time = game.get('commence_time', '')
        game_slot = 'EVENING'
        if commence_time:
            try:
                dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                et = dt.astimezone(ZoneInfo('America/New_York'))
                game_slot = classify_game_slot(et)
            except:
                pass

        # Generate thesis
        game_data = {
            'home_team': home_team,
            'away_team': away_team,
            'game_total': game_total,
            'spread': spread,
        }
        thesis = self.thesis_generator.generate_thesis(game_data, legs)

        # Build parlay
        parlay = {
            'id': str(uuid.uuid4()),
            'parlay_type': 'primary',
            'game_id': game_id,
            'game_date': str(target_date),
            'home_team': home_team,
            'away_team': away_team,
            'game_slot': game_slot,
            'total_legs': len(legs),
            'combined_odds': combined_odds,
            'implied_probability': 1 / (1 + combined_odds / 100) if combined_odds > 0 else 0.5,
            'thesis': thesis,
            'season': season_info['season'],
            'season_type': season_info['season_type'],
            'legs': legs,
        }

        # Save to database (unless dry run)
        if not self.dry_run:
            try:
                self.db.save_parlay(parlay)
                print(f"    Saved parlay: {len(legs)} legs, +{combined_odds}")
            except Exception as e:
                logger.error(f"Failed to save parlay: {e}")
                self.results['errors'].append(f"Save parlay: {e}")
        else:
            print(f"    [DRY RUN] Would save parlay: {len(legs)} legs")

        parlays.append(parlay)
        return parlays

    def _confidence_tier(self, confidence: float) -> str:
        """Convert confidence score to tier label."""
        if confidence >= 0.7:
            return 'very_high'
        elif confidence >= 0.55:
            return 'high'
        elif confidence >= 0.40:
            return 'medium'
        else:
            return 'low'

    def _print_summary(self):
        """Print pipeline summary."""
        print("\n" + "=" * 80)
        print("PIPELINE SUMMARY")
        print("=" * 80)

        if self.results['settlement']:
            s = self.results['settlement']
            print(f"\nSettlement ({s.get('date', 'N/A')}):")
            print(f"  Parlays checked: {s.get('parlays_checked', 0)}")
            print(f"  Parlays settled: {s.get('parlays_settled', 0)}")
            if s.get('error'):
                print(f"  Error: {s['error']}")

        if self.results['sgp']:
            g = self.results['sgp']
            print(f"\nSGP Generation ({g.get('date', 'N/A')}):")
            print(f"  Games found: {g.get('games_found', 0)}")
            print(f"  Parlays generated: {g.get('parlays_generated', 0)}")
            print(f"  Total legs: {g.get('total_legs', 0)}")
            if g.get('error'):
                print(f"  Error: {g['error']}")

        if self.results['errors']:
            print("\nErrors:")
            for err in self.results['errors']:
                print(f"  - {err}")

        print("\n" + "=" * 80)


# =============================================================================
# CLI
# =============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='NBA SGP Daily Orchestrator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline for today
  python -m scripts.nba_daily_orchestrator

  # Settlement only (morning run)
  python -m scripts.nba_daily_orchestrator --settle-only

  # SGP generation only (afternoon run)
  python -m scripts.nba_daily_orchestrator --generate-only --force-refresh

  # Specific date
  python -m scripts.nba_daily_orchestrator --date 2025-12-16

Schedule (Railway cron):
  15:00 UTC (10am ET): --settle-only + --generate-only (morning)
  19:00 UTC (2pm ET):  --generate-only --force-refresh (afternoon)
        """
    )

    parser.add_argument(
        '--date',
        type=str,
        help='Target date in YYYY-MM-DD format (ET). Default: today'
    )
    parser.add_argument(
        '--settle-only',
        action='store_true',
        help='Only run settlement stage'
    )
    parser.add_argument(
        '--generate-only',
        action='store_true',
        help='Only run SGP generation stage'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Don\'t write to database'
    )
    parser.add_argument(
        '--force-refresh',
        action='store_true',
        help='Overwrite existing predictions'
    )
    parser.add_argument(
        '--season-type',
        type=str,
        choices=['regular', 'playoffs', 'cup', 'playin'],
        help='Override season type detection'
    )

    args = parser.parse_args()

    # Parse target date
    target_date = None
    if args.date:
        try:
            target_date = parse_date_et(args.date)
        except ValueError:
            print(f"Error: Invalid date format: {args.date}")
            print("Use YYYY-MM-DD format")
            sys.exit(1)

    # Create orchestrator
    orchestrator = NBADailyOrchestrator(
        dry_run=args.dry_run,
        force_refresh=args.force_refresh,
    )

    # Run pipeline
    results = orchestrator.run(
        target_date=target_date,
        settle_only=args.settle_only,
        generate_only=args.generate_only,
    )

    # Exit with error code if there were errors
    if results.get('errors'):
        sys.exit(1)


if __name__ == '__main__':
    main()
