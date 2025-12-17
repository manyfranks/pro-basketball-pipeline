#!/usr/bin/env python3
"""
NBA SGP Engine - Daily Run Script

Orchestrates daily operations for the NBA SGP Engine.
Designed to run as cron jobs on Railway.

Modes:
    generate: Fetch props, calculate edges, save parlays
    settle: Settle yesterday's parlays against box scores
    refresh: Re-fetch props with updated injury data

Usage:
    python scripts/daily_run.py --mode=generate
    python scripts/daily_run.py --mode=settle
    python scripts/daily_run.py --mode=refresh
"""

import os
import sys
import argparse
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
logger = logging.getLogger('daily_run')

ET = ZoneInfo('America/New_York')


def generate_parlays(target_date: date = None):
    """
    Generate parlays for today's games.

    1. Fetch today's games from Odds API
    2. For each game with props:
       - Build context for each prop
       - Calculate edges
       - Select top 3 edges for parlay
    3. Save parlays to database
    """
    from src.orchestrator import NBAOrchestrator

    if target_date is None:
        target_date = datetime.now(ET).date()

    logger.info(f"=== GENERATING PARLAYS FOR {target_date} ===")

    try:
        orchestrator = NBAOrchestrator()
        result = orchestrator.run_daily_analysis(game_date=target_date)

        logger.info(f"Generated {result.get('parlays_saved', 0)} parlays")
        logger.info(f"Total legs: {result.get('total_legs', 0)}")

        return result

    except Exception as e:
        logger.error(f"Error generating parlays: {e}")
        raise


def settle_parlays(settle_date: date = None):
    """
    Settle parlays from yesterday.

    1. Get unsettled parlays for the date
    2. Fetch box scores from nba_api
    3. Compare actual stats to prop lines
    4. Update leg results and parlay settlement
    """
    from src.settlement import SettlementEngine
    from src.db_manager import get_db_manager

    if settle_date is None:
        # Default to yesterday
        settle_date = datetime.now(ET).date() - timedelta(days=1)

    logger.info(f"=== SETTLING PARLAYS FOR {settle_date} ===")

    try:
        db = get_db_manager()
        engine = SettlementEngine(db)
        result = engine.settle_date(settle_date)

        logger.info(f"Settled: {result.get('parlays_settled', 0)} parlays")
        logger.info(f"Results: {result.get('wins', 0)}W / {result.get('losses', 0)}L / {result.get('voids', 0)}V")

        if result.get('errors'):
            for error in result['errors']:
                logger.warning(f"Settlement error: {error}")

        return result

    except Exception as e:
        logger.error(f"Error settling parlays: {e}")
        raise


def refresh_parlays(target_date: date = None):
    """
    Refresh parlays with updated data.

    Use case: Run after injury report (5 PM ET) to update
    confidence scores based on new injury data.
    """
    if target_date is None:
        target_date = datetime.now(ET).date()

    logger.info(f"=== REFRESHING PARLAYS FOR {target_date} ===")

    # For now, just regenerate
    # Future: Could update existing parlays without recreating
    return generate_parlays(target_date)


def health_check():
    """Run health checks on all dependencies."""
    logger.info("=== HEALTH CHECK ===")

    checks = {
        'database': False,
        'odds_api': False,
        'nba_api': False,
    }

    # Database
    try:
        from src.db_manager import get_db_manager
        db = get_db_manager()
        checks['database'] = db.test_connection()
    except Exception as e:
        logger.error(f"Database check failed: {e}")

    # Odds API
    try:
        api_key = os.environ.get('ODDS_API_KEY')
        checks['odds_api'] = bool(api_key)
    except Exception as e:
        logger.error(f"Odds API check failed: {e}")

    # nba_api
    try:
        from nba_api.stats.static import players
        all_players = players.get_active_players()
        checks['nba_api'] = len(all_players) > 0
    except Exception as e:
        logger.error(f"NBA API check failed: {e}")

    for service, status in checks.items():
        status_str = "OK" if status else "FAILED"
        logger.info(f"  {service}: {status_str}")

    return all(checks.values())


def main():
    parser = argparse.ArgumentParser(description='NBA SGP Daily Run')
    parser.add_argument(
        '--mode',
        type=str,
        choices=['generate', 'settle', 'refresh', 'health'],
        default='generate',
        help='Run mode'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Target date (YYYY-MM-DD). Defaults to today/yesterday based on mode.'
    )

    args = parser.parse_args()

    # Parse date if provided
    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    # Run based on mode
    if args.mode == 'generate':
        generate_parlays(target_date)
    elif args.mode == 'settle':
        settle_parlays(target_date)
    elif args.mode == 'refresh':
        refresh_parlays(target_date)
    elif args.mode == 'health':
        success = health_check()
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
