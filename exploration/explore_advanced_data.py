#!/usr/bin/env python3
"""
NBA API Advanced Data Exploration

Queries all data points needed for the SGP engine:
1. Pace/Tempo data (team possessions per game)
2. Defense vs Position matchups
3. High-value target identification (starter filter)
4. Schedule analysis (B2B, 3-in-4 detection)
5. Home/Away splits
"""

import time
from datetime import datetime, timedelta
from pprint import pprint
import pandas as pd

from nba_api.stats.endpoints import (
    playergamelog,
    leaguedashplayerstats,
    leaguedashteamstats,
    teamdashboardbygeneralsplits,
    teamgamelog,
    scoreboardv2,
    leaguedashptdefend,
)
from nba_api.stats.static import players, teams


def section(title: str):
    print(f"\n{'='*70}")
    print(f" {title}")
    print(f"{'='*70}\n")


# =============================================================================
# 1. PACE/TEMPO DATA
# =============================================================================

def explore_pace_data():
    """Get team pace (possessions per game) for all teams."""
    section("1. PACE/TEMPO DATA")

    time.sleep(0.6)
    team_stats = leaguedashteamstats.LeagueDashTeamStats(
        season='2024-25',
        per_mode_detailed='PerGame',
        measure_type_detailed_defense='Advanced'
    )

    df = team_stats.get_data_frames()[0]

    # Find pace-related columns
    pace_cols = [c for c in df.columns if 'PACE' in c or 'POSS' in c]
    print(f"Pace-related columns: {pace_cols}")

    if 'PACE' in df.columns:
        print(f"\nTeam Pace Rankings (possessions per 48 min):")
        pace_df = df[['TEAM_NAME', 'PACE']].sort_values('PACE', ascending=False)
        print(pace_df.head(10).to_string(index=False))
        print("...")
        print(pace_df.tail(5).to_string(index=False))

        print(f"\nPace Range: {df['PACE'].min():.1f} - {df['PACE'].max():.1f}")
        print(f"League Average: {df['PACE'].mean():.1f}")

        return df[['TEAM_ID', 'TEAM_NAME', 'TEAM_ABBREVIATION', 'PACE']]

    return None


# =============================================================================
# 2. DEFENSE VS POSITION
# =============================================================================

def explore_defense_vs_position():
    """Get how teams defend against different positions."""
    section("2. DEFENSE VS POSITION MATCHUPS")

    time.sleep(0.6)

    # LeagueDashPtDefend gives us defense by position
    try:
        defense = leaguedashptdefend.LeagueDashPtDefend(
            season='2024-25',
            defense_category='Overall',
            per_mode_simple='PerGame'
        )
        df = defense.get_data_frames()[0]
        print(f"Defense columns: {df.columns.tolist()}")
        print(f"\nSample data:")
        print(df.head(10))
        return df
    except Exception as e:
        print(f"LeagueDashPtDefend error: {e}")

    # Fallback: Use team defensive rating
    print("\nFallback: Using team defensive ratings...")
    time.sleep(0.6)

    team_stats = leaguedashteamstats.LeagueDashTeamStats(
        season='2024-25',
        per_mode_detailed='PerGame',
        measure_type_detailed_defense='Advanced'
    )

    df = team_stats.get_data_frames()[0]
    def_cols = [c for c in df.columns if 'DEF' in c]
    print(f"Defensive columns: {def_cols}")

    if 'DEF_RATING' in df.columns:
        print(f"\nTeam Defensive Ratings (lower = better):")
        def_df = df[['TEAM_NAME', 'DEF_RATING']].sort_values('DEF_RATING')
        print(def_df.head(10).to_string(index=False))

        return df[['TEAM_ID', 'TEAM_NAME', 'TEAM_ABBREVIATION', 'DEF_RATING']]

    return None


# =============================================================================
# 3. HIGH-VALUE TARGET FILTER
# =============================================================================

def explore_high_value_targets():
    """Identify players who meet our 'starter' criteria."""
    section("3. HIGH-VALUE TARGET FILTER")

    time.sleep(0.6)

    # Get league-wide player stats with advanced metrics
    player_stats = leaguedashplayerstats.LeagueDashPlayerStats(
        season='2024-25',
        per_mode_detailed='PerGame',
        measure_type_detailed_defense='Base'
    )

    df = player_stats.get_data_frames()[0]

    print(f"Total players: {len(df)}")
    print(f"Columns: {df.columns.tolist()[:15]}...")

    # Define high-value target criteria
    # MIN >= 25, GP >= 15
    high_value = df[
        (df['MIN'] >= 25) &
        (df['GP'] >= 15)
    ].copy()

    print(f"\nHigh-value targets (MIN >= 25, GP >= 15): {len(high_value)}")
    print(f"Percentage of players: {len(high_value)/len(df)*100:.1f}%")

    # Show top high-value targets by points
    print(f"\nTop 15 High-Value Targets by PPG:")
    cols = ['PLAYER_NAME', 'TEAM_ABBREVIATION', 'GP', 'MIN', 'PTS', 'REB', 'AST']
    print(high_value.nlargest(15, 'PTS')[cols].to_string(index=False))

    # Now get usage rate data
    print("\n--- Adding Usage Rate ---")
    time.sleep(0.6)

    advanced_stats = leaguedashplayerstats.LeagueDashPlayerStats(
        season='2024-25',
        per_mode_detailed='PerGame',
        measure_type_detailed_defense='Advanced'
    )

    adv_df = advanced_stats.get_data_frames()[0]

    if 'USG_PCT' in adv_df.columns:
        # Merge usage data
        merged = high_value.merge(
            adv_df[['PLAYER_ID', 'USG_PCT']],
            on='PLAYER_ID',
            how='left'
        )

        # Filter by usage >= 18%
        high_usage = merged[merged['USG_PCT'] >= 0.18]
        print(f"\nHigh-value + High-usage (USG >= 18%): {len(high_usage)}")

        print(f"\nTop 15 by Usage Rate:")
        cols = ['PLAYER_NAME', 'TEAM_ABBREVIATION', 'MIN', 'USG_PCT', 'PTS']
        print(high_usage.nlargest(15, 'USG_PCT')[cols].to_string(index=False))

        return high_usage

    return high_value


# =============================================================================
# 4. SCHEDULE ANALYSIS (B2B, 3-in-4)
# =============================================================================

def explore_schedule_patterns():
    """Analyze schedule for B2B and 3-in-4 patterns."""
    section("4. SCHEDULE ANALYSIS (B2B, 3-in-4)")

    time.sleep(0.6)

    # Get Lakers schedule as example
    lakers = teams.find_team_by_abbreviation("LAL")
    team_log = teamgamelog.TeamGameLog(
        team_id=lakers['id'],
        season='2024-25'
    )

    df = team_log.get_data_frames()[0]
    print(f"Games in schedule: {len(df)}")
    print(f"Columns: {df.columns.tolist()}")

    # Parse dates and detect B2B
    df['GAME_DATE_PARSED'] = pd.to_datetime(df['GAME_DATE'], format='%b %d, %Y')
    df = df.sort_values('GAME_DATE_PARSED')

    # Calculate days since last game
    df['DAYS_REST'] = df['GAME_DATE_PARSED'].diff().dt.days

    # Detect B2B (0 or 1 day rest)
    df['IS_B2B'] = df['DAYS_REST'] <= 1

    # Detect 3-in-4 (look at 4-day windows)
    df['IS_3_IN_4'] = False
    for i in range(2, len(df)):
        window_start = df.iloc[i]['GAME_DATE_PARSED'] - timedelta(days=3)
        games_in_window = df[
            (df['GAME_DATE_PARSED'] >= window_start) &
            (df['GAME_DATE_PARSED'] <= df.iloc[i]['GAME_DATE_PARSED'])
        ]
        if len(games_in_window) >= 3:
            df.iloc[i, df.columns.get_loc('IS_3_IN_4')] = True

    print(f"\nLakers Schedule Sample (last 15 games):")
    cols = ['GAME_DATE', 'MATCHUP', 'WL', 'DAYS_REST', 'IS_B2B', 'IS_3_IN_4', 'PTS']
    print(df.tail(15)[cols].to_string(index=False))

    b2b_count = df['IS_B2B'].sum()
    three_in_four_count = df['IS_3_IN_4'].sum()

    print(f"\nSchedule Summary:")
    print(f"  Back-to-backs: {b2b_count} ({b2b_count/len(df)*100:.1f}%)")
    print(f"  3-in-4 nights: {three_in_four_count} ({three_in_four_count/len(df)*100:.1f}%)")

    # Performance impact
    b2b_games = df[df['IS_B2B'] == True]
    non_b2b_games = df[df['IS_B2B'] == False]

    if len(b2b_games) > 0 and len(non_b2b_games) > 0:
        print(f"\nPerformance Impact:")
        print(f"  B2B games avg points: {b2b_games['PTS'].mean():.1f}")
        print(f"  Non-B2B games avg points: {non_b2b_games['PTS'].mean():.1f}")
        print(f"  Delta: {b2b_games['PTS'].mean() - non_b2b_games['PTS'].mean():.1f}")

    return df


# =============================================================================
# 5. HOME/AWAY SPLITS
# =============================================================================

def explore_home_away_splits():
    """Get home vs away performance splits."""
    section("5. HOME/AWAY SPLITS")

    time.sleep(0.6)

    # Get LeBron's game log
    lebron = players.find_players_by_full_name("LeBron James")[0]
    gamelog = playergamelog.PlayerGameLog(
        player_id=lebron['id'],
        season='2024-25'
    )

    df = gamelog.get_data_frames()[0]

    # Detect home/away from MATCHUP column
    # "LAL vs. XXX" = home, "LAL @ XXX" = away
    df['IS_HOME'] = df['MATCHUP'].str.contains('vs.')

    home_games = df[df['IS_HOME'] == True]
    away_games = df[df['IS_HOME'] == False]

    print(f"LeBron James Home/Away Splits:")
    print(f"\n  Home Games: {len(home_games)}")
    print(f"    PPG: {home_games['PTS'].mean():.1f}")
    print(f"    RPG: {home_games['REB'].mean():.1f}")
    print(f"    APG: {home_games['AST'].mean():.1f}")

    print(f"\n  Away Games: {len(away_games)}")
    print(f"    PPG: {away_games['PTS'].mean():.1f}")
    print(f"    RPG: {away_games['REB'].mean():.1f}")
    print(f"    APG: {away_games['AST'].mean():.1f}")

    print(f"\n  Delta (Home - Away):")
    print(f"    PPG: {home_games['PTS'].mean() - away_games['PTS'].mean():+.1f}")
    print(f"    RPG: {home_games['REB'].mean() - away_games['REB'].mean():+.1f}")
    print(f"    APG: {home_games['AST'].mean() - away_games['AST'].mean():+.1f}")

    return df


# =============================================================================
# 6. TODAY'S GAMES WITH ENRICHED DATA
# =============================================================================

def explore_todays_games_enriched():
    """Get today's games with pace and defensive ratings."""
    section("6. TODAY'S GAMES (ENRICHED)")

    time.sleep(0.6)

    # Get today's scoreboard
    today = datetime.now().strftime('%Y-%m-%d')
    scoreboard = scoreboardv2.ScoreboardV2(game_date=today)

    games_df = scoreboard.get_data_frames()[0]
    print(f"Games on {today}: {len(games_df)}")

    if games_df.empty:
        print("No games today. Checking tomorrow...")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        scoreboard = scoreboardv2.ScoreboardV2(game_date=tomorrow)
        games_df = scoreboard.get_data_frames()[0]
        print(f"Games on {tomorrow}: {len(games_df)}")

    if not games_df.empty:
        # Get team data for enrichment
        all_teams = {t['id']: t for t in teams.get_teams()}

        print("\nGames with Team Info:")
        for _, game in games_df.iterrows():
            home_id = game['HOME_TEAM_ID']
            away_id = game['VISITOR_TEAM_ID']
            home_team = all_teams.get(home_id, {}).get('abbreviation', 'UNK')
            away_team = all_teams.get(away_id, {}).get('abbreviation', 'UNK')
            status = game['GAME_STATUS_TEXT']
            print(f"  {away_team} @ {home_team} - {status}")

    return games_df


# =============================================================================
# SUMMARY
# =============================================================================

def print_summary():
    section("SUMMARY: Data Points for NBA SGP Engine")

    print("""
    DATA PROVIDER REQUIREMENTS:
    ══════════════════════════════════════════════════════════════════

    1. PACE DATA ✓
       └── leaguedashteamstats (Advanced) → PACE column
       └── Use: Correlation signal (high pace = more stats)

    2. DEFENSE RATINGS ✓
       └── leaguedashteamstats (Advanced) → DEF_RATING column
       └── Use: Matchup signal (weak defense = more scoring)

    3. HIGH-VALUE TARGET FILTER ✓
       └── leaguedashplayerstats → MIN >= 25, GP >= 15
       └── leaguedashplayerstats (Advanced) → USG_PCT >= 18%
       └── Use: Filter out low-minute players (NHL's "scoreable" equivalent)

    4. SCHEDULE PATTERNS ✓
       └── teamgamelog → GAME_DATE for B2B/3-in-4 detection
       └── Use: Environment signal (fatigue adjustment)

    5. HOME/AWAY SPLITS ✓
       └── playergamelog → MATCHUP contains "vs." or "@"
       └── Use: Environment signal (home court advantage)

    6. PLAYER GAME LOGS ✓ (from initial exploration)
       └── playergamelog → PTS, REB, AST, STL, BLK, FG3M, MIN
       └── Use: Trend signal, Usage signal

    STILL NEEDED:
    ══════════════════════════════════════════════════════════════════

    7. INJURY/AVAILABILITY (STUB FOR NOW)
       └── External source needed (ESPN, Rotowire)
       └── Critical for avoiding bets on resting stars

    8. ODDS API INTEGRATION
       └── Game totals, spreads (for correlation signal)
       └── Player props with alternate lines
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print(" NBA API ADVANCED DATA EXPLORATION")
    print(" Gathering all data points for SGP Engine")
    print("="*70)

    # 1. Pace data
    pace_df = explore_pace_data()

    # 2. Defense vs position
    defense_df = explore_defense_vs_position()

    # 3. High-value targets
    high_value_df = explore_high_value_targets()

    # 4. Schedule patterns
    schedule_df = explore_schedule_patterns()

    # 5. Home/away splits
    splits_df = explore_home_away_splits()

    # 6. Today's games
    games_df = explore_todays_games_enriched()

    # Summary
    print_summary()

    print("\n✅ Advanced exploration complete!")
