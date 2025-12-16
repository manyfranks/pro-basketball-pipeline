#!/usr/bin/env python3
"""
NBA API Exploration Script

Explores the nba_api library to understand available data for SGP signal generation.
Key areas to investigate:
1. Player game logs (trend signal)
2. Player season stats (baseline)
3. Team defensive stats (matchup signal)
4. Schedule/scoreboard (environment signal)
"""

import time
from datetime import datetime, timedelta
from pprint import pprint

# nba_api imports
from nba_api.stats.endpoints import (
    playergamelog,
    commonplayerinfo,
    playercareerstats,
    leaguedashplayerstats,
    teamdashboardbygeneralsplits,
    scoreboardv2,
    leaguegamefinder,
    teamgamelog,
)
from nba_api.stats.static import players, teams


def section(title: str):
    """Print section header."""
    print(f"\n{'='*70}")
    print(f" {title}")
    print(f"{'='*70}\n")


def explore_static_data():
    """Explore static player/team data."""
    section("1. STATIC DATA (Players & Teams)")

    # Get all active players
    all_players = players.get_active_players()
    print(f"Total active players: {len(all_players)}")
    print(f"\nSample player record:")
    pprint(all_players[0])

    # Find a specific player
    lebron = players.find_players_by_full_name("LeBron James")
    print(f"\nLeBron James lookup:")
    pprint(lebron)

    # Get all teams
    all_teams = teams.get_teams()
    print(f"\nTotal teams: {len(all_teams)}")
    print(f"\nSample team record:")
    pprint(all_teams[0])

    return lebron[0]['id'] if lebron else None


def explore_player_game_log(player_id: int):
    """Explore player game logs - KEY for trend signal."""
    section("2. PLAYER GAME LOG (Trend Signal)")

    # Get current season game log
    time.sleep(0.6)  # Rate limiting
    gamelog = playergamelog.PlayerGameLog(
        player_id=player_id,
        season='2024-25',
        season_type_all_star='Regular Season'
    )

    df = gamelog.get_data_frames()[0]
    print(f"Games played this season: {len(df)}")
    print(f"\nColumns available:")
    print(df.columns.tolist())

    print(f"\nLast 5 games:")
    cols = ['GAME_DATE', 'MATCHUP', 'WL', 'MIN', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'FG3M', 'TOV']
    print(df[cols].head())

    # Calculate L5 vs Season averages
    if len(df) >= 5:
        l5 = df.head(5)
        season = df

        print(f"\n--- TREND ANALYSIS ---")
        for stat in ['PTS', 'REB', 'AST', 'STL', 'BLK', 'FG3M']:
            l5_avg = l5[stat].mean()
            season_avg = season[stat].mean()
            pct_diff = ((l5_avg - season_avg) / season_avg * 100) if season_avg > 0 else 0
            direction = "↑" if pct_diff > 0 else "↓"
            print(f"  {stat}: L5={l5_avg:.1f} vs Season={season_avg:.1f} ({pct_diff:+.1f}% {direction})")

    return df


def explore_player_career_stats(player_id: int):
    """Explore player career/season stats."""
    section("3. PLAYER CAREER STATS (Season Baseline)")

    time.sleep(0.6)
    career = playercareerstats.PlayerCareerStats(player_id=player_id)

    # Regular season stats by year
    df = career.get_data_frames()[0]  # SeasonTotalsRegularSeason
    print(f"Seasons played: {len(df)}")
    print(f"\nCurrent season stats:")
    current = df[df['SEASON_ID'] == '2024-25']
    if not current.empty:
        cols = ['SEASON_ID', 'TEAM_ABBREVIATION', 'GP', 'MIN', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'FG3M']
        print(current[cols].to_string(index=False))


def explore_league_player_stats():
    """Explore league-wide player stats - useful for rankings."""
    section("4. LEAGUE PLAYER STATS (Rankings)")

    time.sleep(0.6)
    league_stats = leaguedashplayerstats.LeagueDashPlayerStats(
        season='2024-25',
        per_mode_detailed='PerGame'
    )

    df = league_stats.get_data_frames()[0]
    print(f"Total players with stats: {len(df)}")
    print(f"\nColumns available ({len(df.columns)}):")
    print(df.columns.tolist()[:20])
    print("...")

    # Top 5 scorers
    print(f"\nTop 5 PPG:")
    top_scorers = df.nlargest(5, 'PTS')[['PLAYER_NAME', 'TEAM_ABBREVIATION', 'GP', 'MIN', 'PTS', 'REB', 'AST']]
    print(top_scorers.to_string(index=False))


def explore_team_defense():
    """Explore team defensive stats - KEY for matchup signal."""
    section("5. TEAM DEFENSIVE STATS (Matchup Signal)")

    time.sleep(0.6)

    # Get team defensive dashboard
    # Note: This gives us points allowed, defensive rating, etc.
    lakers = teams.find_team_by_abbreviation("LAL")

    team_stats = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
        team_id=lakers['id'],
        season='2024-25',
        per_mode_detailed='PerGame'
    )

    df = team_stats.get_data_frames()[0]  # OverallTeamDashboard
    print(f"Lakers defensive stats this season:")
    print(f"Columns: {df.columns.tolist()}")

    if not df.empty:
        # Defensive-relevant columns
        def_cols = [c for c in df.columns if 'DEF' in c or 'OPP' in c or 'PLUS_MINUS' in c]
        print(f"\nDefensive columns: {def_cols}")


def explore_schedule():
    """Explore today's schedule - for knowing which games to analyze."""
    section("6. TODAY'S SCHEDULE (Game Selection)")

    time.sleep(0.6)

    # Get today's scoreboard
    today = datetime.now().strftime('%Y-%m-%d')
    scoreboard = scoreboardv2.ScoreboardV2(game_date=today)

    games_df = scoreboard.get_data_frames()[0]  # GameHeader
    print(f"Games on {today}: {len(games_df)}")

    if not games_df.empty:
        print(f"\nColumns: {games_df.columns.tolist()}")
        print(f"\nToday's games:")
        cols = ['GAME_ID', 'GAME_STATUS_TEXT', 'HOME_TEAM_ID', 'VISITOR_TEAM_ID']
        available_cols = [c for c in cols if c in games_df.columns]
        print(games_df[available_cols])
    else:
        print("No games today. Checking tomorrow...")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        scoreboard = scoreboardv2.ScoreboardV2(game_date=tomorrow)
        games_df = scoreboard.get_data_frames()[0]
        print(f"Games on {tomorrow}: {len(games_df)}")


def explore_usage_metrics():
    """Explore usage rate and advanced stats."""
    section("7. ADVANCED STATS (Usage Signal)")

    time.sleep(0.6)

    # League stats with advanced metrics
    advanced = leaguedashplayerstats.LeagueDashPlayerStats(
        season='2024-25',
        per_mode_detailed='PerGame',
        measure_type_detailed_defense='Advanced'  # Get advanced stats
    )

    try:
        df = advanced.get_data_frames()[0]
        print(f"Advanced stat columns:")
        adv_cols = [c for c in df.columns if 'USG' in c or 'PACE' in c or 'PIE' in c or 'POSS' in c]
        print(adv_cols)

        if 'USG_PCT' in df.columns:
            print(f"\nTop 5 by Usage Rate:")
            top_usage = df.nlargest(5, 'USG_PCT')[['PLAYER_NAME', 'TEAM_ABBREVIATION', 'USG_PCT', 'MIN', 'PTS']]
            print(top_usage.to_string(index=False))
    except Exception as e:
        print(f"Advanced stats error: {e}")


def summarize_for_sgp():
    """Summarize which endpoints are useful for SGP signals."""
    section("SUMMARY: NBA API → SGP Signals Mapping")

    print("""
    TREND SIGNAL:
    └── playergamelog.PlayerGameLog
        - Last N games vs season average
        - Stats: PTS, REB, AST, STL, BLK, FG3M, TOV, MIN

    USAGE SIGNAL:
    └── playergamelog.PlayerGameLog + leaguedashplayerstats
        - Minutes trending up/down
        - Shot attempts, touches, usage rate
        - Recent role changes

    MATCHUP SIGNAL:
    └── teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits
        - Team defensive rating
        - Points allowed by position (need additional endpoint)
        - Pace factor

    ENVIRONMENT SIGNAL:
    └── scoreboardv2.ScoreboardV2 + team schedule
        - Back-to-back detection
        - Home/away
        - Rest days

    CORRELATION SIGNAL:
    └── From Odds API (game total, spread)
        - High total → more scoring opportunities
        - Large spread → garbage time risk

    KEY PROP TYPES TO SUPPORT:
    ├── Points (PTS)
    ├── Rebounds (REB)
    ├── Assists (AST)
    ├── 3-Pointers Made (FG3M)
    ├── Steals (STL)
    ├── Blocks (BLK)
    ├── Points+Rebounds+Assists (PTS+REB+AST)
    ├── Points+Rebounds (PTS+REB)
    ├── Points+Assists (PTS+AST)
    └── Rebounds+Assists (REB+AST)
    """)


if __name__ == "__main__":
    print("\n" + "="*70)
    print(" NBA API EXPLORATION FOR SGP ENGINE")
    print("="*70)

    # 1. Static data
    player_id = explore_static_data()

    if player_id:
        # 2. Player game log (most important for signals)
        explore_player_game_log(player_id)

        # 3. Career stats
        explore_player_career_stats(player_id)

    # 4. League-wide stats
    explore_league_player_stats()

    # 5. Team defense
    explore_team_defense()

    # 6. Schedule
    explore_schedule()

    # 7. Usage/Advanced
    explore_usage_metrics()

    # Summary
    summarize_for_sgp()

    print("\n✅ Exploration complete!")
