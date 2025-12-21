#!/usr/bin/env python3
"""
NBA SGP Week Scheduler

Determines if jobs should run based on current time.
Designed for Railway deployment with hourly cron.

Modeled after nfl-touchdown-pipeline/scheduler/nfl_week_scheduler.py

Usage:
    # Default: Run scheduled jobs based on current time
    python -m scheduler.nba_scheduler

    # Force run all jobs (for testing)
    python -m scheduler.nba_scheduler --force

    # Check current status
    python -m scheduler.nba_scheduler --check

    # Run specific job manually
    python -m scheduler.nba_scheduler --job morning

Railway Setup:
    1. Set cronSchedule = "0 * * * *" (hourly) in railway.toml
    2. The scheduler checks current hour and runs appropriate jobs
    3. Morning: 15:00 UTC (10am ET) - Settlement + SGP
    4. Afternoon: 19:00 UTC (2pm ET) - SGP refresh
"""

import os
import sys
import subprocess
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Tuple, Optional, Dict, Any
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NBAScheduler:
    """
    Handles NBA season detection and pipeline scheduling.

    The scheduler runs hourly via Railway cron and checks if any jobs
    should run at the current hour. This allows multiple run times
    without needing multiple Railway services.
    """

    # NBA Season Configuration
    SEASON_CONFIG = {
        2026: {  # 2025-26 Season (keyed by ending year)
            'preseason_start': date(2025, 10, 3),
            'regular_season_start': date(2025, 10, 21),
            'allstar_start': date(2026, 2, 13),
            'allstar_end': date(2026, 2, 18),
            'regular_season_end': date(2026, 4, 12),
            'playoffs_end': date(2026, 6, 21),
        },
        2027: {  # 2026-27 Season
            'preseason_start': date(2026, 10, 2),
            'regular_season_start': date(2026, 10, 20),
            'allstar_start': date(2027, 2, 12),
            'allstar_end': date(2027, 2, 17),
            'regular_season_end': date(2027, 4, 11),
            'playoffs_end': date(2027, 6, 20),
        }
    }

    def __init__(self, season: Optional[int] = None):
        """
        Initialize scheduler.

        Args:
            season: Season year (ending year, e.g., 2026 for 2025-26).
                   Auto-detected if not provided.
        """
        self.season = season or self._detect_season()
        self.config = self._get_season_config()
        logger.info(f"NBA Scheduler initialized for {self.season} season")

    def _detect_season(self) -> int:
        """
        Detect current NBA season based on date.

        NBA seasons span two calendar years (Oct-June).
        We use the ending year as the season identifier.
        """
        now = datetime.now(timezone.utc)
        # If Oct-Dec: upcoming season (year + 1)
        # If Jan-Sep: current season (year)
        if now.month >= 10:
            return now.year + 1
        return now.year

    def _get_season_config(self) -> Dict:
        """Get config for current season, with fallback generation."""
        if self.season in self.SEASON_CONFIG:
            return self.SEASON_CONFIG[self.season]

        # Generate config based on 2026 template
        base = self.SEASON_CONFIG[2026]
        year_diff = self.season - 2026

        return {
            k: v.replace(year=v.year + year_diff) if isinstance(v, date) else v
            for k, v in base.items()
        }

    def get_season_phase(self, as_of_date: Optional[date] = None) -> Tuple[str, bool]:
        """
        Determine current season phase.

        Args:
            as_of_date: Date to check (default: today in ET)

        Returns:
            Tuple of (phase_name, should_run)
        """
        from zoneinfo import ZoneInfo

        if as_of_date is None:
            # Use Eastern Time for NBA operations
            et = ZoneInfo('America/New_York')
            as_of_date = datetime.now(et).date()

        cfg = self.config

        if as_of_date < cfg['preseason_start']:
            return 'offseason', False

        if as_of_date < cfg['regular_season_start']:
            return 'preseason', False

        if cfg['allstar_start'] <= as_of_date <= cfg['allstar_end']:
            return 'allstar_break', False

        if as_of_date > cfg['playoffs_end']:
            return 'offseason', False

        if as_of_date > cfg['regular_season_end']:
            return 'playoffs', True

        return 'regular', True

    def get_pipeline_schedule(self) -> Dict[str, Dict]:
        """
        Get the pipeline schedule.

        Returns dict of job configurations with:
        - hour: UTC hour to run
        - minute: UTC minute (default 0)
        - command: Command to execute
        - description: Human-readable description
        """
        schedule = {
            # Morning Run - 15:00 UTC = 10am ET = 7am PT
            # Settlement + SGP generation
            'morning': {
                'hour': 15,
                'minute': 0,
                'command': f'python -m scripts.nba_daily_orchestrator',
                'description': 'Morning: Settlement + SGP generation',
            },

            # Afternoon Run - 19:00 UTC = 2pm ET = 11am PT
            # Final SGP after injury reports
            'afternoon': {
                'hour': 19,
                'minute': 0,
                'command': f'python -m scripts.nba_daily_orchestrator --generate-only --force-refresh',
                'description': 'Afternoon: Final SGP after injury cutoff',
            },
        }

        return schedule

    def should_run_job(
        self,
        job_name: str,
        current_time: Optional[datetime] = None
    ) -> bool:
        """
        Check if a specific job should run now.

        Args:
            job_name: Job name from schedule ('morning', 'afternoon')
            current_time: Optional datetime to check (for testing)

        Returns:
            True if job should run within the current window
        """
        now = current_time or datetime.now(timezone.utc)

        # Check season phase
        phase, should_run = self.get_season_phase()
        if not should_run:
            logger.info(f"In {phase} - no games to process")
            return False

        schedule = self.get_pipeline_schedule()

        if job_name not in schedule:
            logger.warning(f"Unknown job: {job_name}")
            return False

        job_config = schedule[job_name]
        job_hour = job_config['hour']
        job_minute = job_config.get('minute', 0)

        current_hour = now.hour
        current_minute = now.minute

        # Allow 15-minute window for job execution
        # This accommodates Railway cron variance and startup time
        job_total_minutes = job_hour * 60 + job_minute
        current_total_minutes = current_hour * 60 + current_minute

        # Job runs if we're within 0-14 minutes of scheduled time
        if job_total_minutes <= current_total_minutes < job_total_minutes + 15:
            return True

        return False

    def run_scheduled_jobs(self, force: bool = False) -> Dict[str, Any]:
        """
        Run all jobs that are scheduled for now.

        Args:
            force: If True, run all jobs regardless of schedule

        Returns:
            Results dict with job outcomes
        """
        results = {
            'jobs_run': [],
            'jobs_skipped': [],
            'errors': [],
        }

        # Check season phase
        phase, should_run = self.get_season_phase()
        logger.info(f"NBA Scheduler - Season {self.season}, Phase: {phase}")

        if not should_run and not force:
            logger.info(f"In {phase} - no games to process, skipping all jobs")
            return results

        schedule = self.get_pipeline_schedule()

        for job_name, job_config in schedule.items():
            if force or self.should_run_job(job_name):
                logger.info(f"Running {job_name}...")
                success = self._execute_job(job_name, job_config['command'])

                if success:
                    results['jobs_run'].append(job_name)
                else:
                    results['errors'].append(job_name)
            else:
                logger.debug(f"Skipping {job_name} (not scheduled)")
                results['jobs_skipped'].append(job_name)

        if not results['jobs_run']:
            logger.info("No jobs scheduled for current time")

        return results

    def _execute_job(self, job_name: str, command: str) -> bool:
        """
        Execute a scheduled job.

        Args:
            job_name: Name of the job
            command: Command to run

        Returns:
            True if successful
        """
        try:
            # Set up environment
            env = os.environ.copy()
            env['PYTHONPATH'] = str(project_root)

            logger.info(f"Executing: {command}")

            result = subprocess.run(
                command.split(),
                capture_output=True,
                text=True,
                env=env,
                cwd=str(project_root),
                timeout=1800  # 30 minute timeout
            )

            if result.returncode == 0:
                logger.info(f"{job_name} completed successfully")
                if result.stdout:
                    # Log last 500 chars
                    logger.debug(f"Output: ...{result.stdout[-500:]}")
                return True
            else:
                logger.error(f"{job_name} failed (exit code {result.returncode})")
                logger.error(f"stderr: {result.stderr[-1000:] if result.stderr else 'empty'}")
                logger.error(f"stdout: {result.stdout[-1000:] if result.stdout else 'empty'}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"{job_name} timed out after 30 minutes")
            return False
        except Exception as e:
            logger.error(f"Failed to execute {job_name}: {e}")
            return False


def main():
    """Main entry point for scheduler."""
    import argparse

    parser = argparse.ArgumentParser(description='NBA SGP Pipeline Scheduler')
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force run all jobs regardless of schedule'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check current status and schedule without running'
    )
    parser.add_argument(
        '--job',
        choices=['morning', 'afternoon'],
        help='Run specific job only'
    )
    parser.add_argument(
        '--season',
        type=int,
        help='Override season year (ending year, e.g., 2026)'
    )

    args = parser.parse_args()

    # Initialize scheduler
    scheduler = NBAScheduler(season=args.season)

    if args.check:
        # Just show current status
        now = datetime.now(timezone.utc)
        phase, should_run = scheduler.get_season_phase()

        print(f"\nNBA Scheduler Status")
        print("=" * 50)
        print(f"Current Time (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Season: {scheduler.season}")
        print(f"Phase: {phase}")
        print(f"Should Run: {should_run}")

        print(f"\nSchedule:")
        print("-" * 50)
        schedule = scheduler.get_pipeline_schedule()
        for job_name, config in schedule.items():
            will_run = scheduler.should_run_job(job_name)
            status = "[WOULD RUN]" if will_run else "[skip]"
            print(f"  {job_name}: {config['hour']:02d}:{config.get('minute', 0):02d} UTC {status}")
            print(f"    {config['description']}")

        print("")
        return

    if args.job:
        # Run specific job
        logger.info(f"Manually running {args.job}")
        schedule = scheduler.get_pipeline_schedule()

        if args.job in schedule:
            success = scheduler._execute_job(args.job, schedule[args.job]['command'])
            sys.exit(0 if success else 1)
        else:
            logger.error(f"Unknown job: {args.job}")
            sys.exit(1)

    # Default: Run scheduled jobs
    results = scheduler.run_scheduled_jobs(force=args.force)

    # Exit with error if any jobs failed
    if results['errors']:
        sys.exit(1)


if __name__ == '__main__':
    main()
