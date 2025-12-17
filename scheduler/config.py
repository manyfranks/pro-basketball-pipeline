"""
NBA SGP Scheduler Configuration

Defines cron schedules for the NBA daily pipeline.

CRITICAL: All times are in UTC for cron compatibility.
The pipeline internally uses ET for all NBA operations.

Schedule:
    - Morning Run (15:00 UTC = 10am ET = 7am PT)
      Settlement + Early SGP generation

    - Afternoon Run (19:00 UTC = 2pm ET = 11am PT)
      Final SGP after injury report cutoff

Why these times:
    - 10am ET: After overnight news, early enough for morning bettors
    - 2pm ET: After most injury reports are finalized (~1:30pm ET)

Deployment:
    - Railway: Use cron jobs feature
    - Local: Use system cron or task scheduler
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class ScheduleEntry:
    """A scheduled job configuration."""
    name: str
    cron: str  # UTC cron expression
    command: str
    description: str
    enabled: bool = True


# =============================================================================
# NBA SGP SCHEDULE
# =============================================================================

NBA_SCHEDULE: Dict[str, ScheduleEntry] = {
    'morning': ScheduleEntry(
        name='nba_sgp_morning',
        cron='0 15 * * *',  # 15:00 UTC = 10am ET = 7am PT
        command='python -m scripts.nba_daily_orchestrator',
        description='Morning: Settlement + Early SGP generation',
    ),
    'afternoon': ScheduleEntry(
        name='nba_sgp_afternoon',
        cron='0 19 * * *',  # 19:00 UTC = 2pm ET = 11am PT
        command='python -m scripts.nba_daily_orchestrator --generate-only --force-refresh',
        description='Afternoon: Final SGP after injury cutoff',
    ),
}


# =============================================================================
# TIMEZONE REFERENCE
# =============================================================================

TIMEZONE_REFERENCE = """
NBA operates on Eastern Time (ET). Schedulers run in UTC.

Conversion Table:
+----------+----------+----------+
| UTC      | ET       | PT       |
+----------+----------+----------+
| 15:00    | 10:00 AM | 7:00 AM  |  <- Morning run
| 19:00    | 2:00 PM  | 11:00 AM |  <- Afternoon run
+----------+----------+----------+

Daylight Saving Time:
- ET = UTC-5 (EST) or UTC-4 (EDT)
- PT = UTC-8 (PST) or UTC-7 (PDT)

During DST (March-November):
- 15:00 UTC = 11:00 AM EDT = 8:00 AM PDT
- 19:00 UTC = 3:00 PM EDT = 12:00 PM PDT

The schedule uses winter times. During DST, runs will be 1 hour later in local time.
Consider adjusting cron times seasonally if precise local times matter.
"""


# =============================================================================
# RAILWAY CONFIG
# =============================================================================

def generate_railway_config() -> Dict[str, Any]:
    """
    Generate Railway.toml configuration for cron jobs.

    Returns:
        Dict suitable for writing to railway.toml
    """
    return {
        'build': {
            'builder': 'NIXPACKS',
        },
        'deploy': {
            'numReplicas': 1,
            'sleepApplication': False,  # Keep alive for cron
            'restartPolicyType': 'ON_FAILURE',
        },
        'crons': [
            {
                'name': entry.name,
                'schedule': entry.cron,
                'command': entry.command,
            }
            for entry in NBA_SCHEDULE.values()
            if entry.enabled
        ],
    }


# =============================================================================
# CRONTAB FORMAT
# =============================================================================

def generate_crontab() -> str:
    """
    Generate crontab entries for local/server deployment.

    Returns:
        Crontab-formatted string
    """
    lines = [
        "# NBA SGP Pipeline Schedule",
        "# Times in UTC - adjust for local timezone if needed",
        "# Format: minute hour day-of-month month day-of-week command",
        "",
    ]

    for key, entry in NBA_SCHEDULE.items():
        if entry.enabled:
            lines.append(f"# {entry.description}")
            lines.append(f"{entry.cron} cd /path/to/pro-basketball-pipeline && {entry.command}")
            lines.append("")

    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='NBA SGP Scheduler Configuration')
    parser.add_argument('--crontab', action='store_true', help='Generate crontab entries')
    parser.add_argument('--railway', action='store_true', help='Generate Railway config')
    parser.add_argument('--info', action='store_true', help='Show timezone info')

    args = parser.parse_args()

    if args.crontab:
        print(generate_crontab())
    elif args.railway:
        import json
        print(json.dumps(generate_railway_config(), indent=2))
    elif args.info:
        print(TIMEZONE_REFERENCE)
    else:
        print("NBA SGP Schedule:")
        print("-" * 60)
        for key, entry in NBA_SCHEDULE.items():
            print(f"\n{entry.name}:")
            print(f"  Cron: {entry.cron} (UTC)")
            print(f"  Command: {entry.command}")
            print(f"  Description: {entry.description}")
            print(f"  Enabled: {entry.enabled}")

        print("\n" + "-" * 60)
        print("Use --crontab, --railway, or --info for specific formats")
