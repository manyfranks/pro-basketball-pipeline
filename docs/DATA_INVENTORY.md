# NBA SGP Engine - Data Inventory

**Version**: 1.0
**Last Updated**: December 2025

This document catalogs all data sources, fields, and mappings used by the NBA SGP Engine.

---

## Table of Contents

1. [Data Sources Overview](#1-data-sources-overview)
2. [nba_api Endpoints](#2-nba_api-endpoints)
3. [Odds API Markets](#3-odds-api-markets)
4. [Internal Data Structures](#4-internal-data-structures)
5. [Field Mappings](#5-field-mappings)
6. [Caching Strategy](#6-caching-strategy)

---

## 1. Data Sources Overview

| Source | Type | Purpose | Rate Limit |
|--------|------|---------|------------|
| `nba_api` | Python package | Player stats, team stats, schedules | ~0.6s between calls |
| Odds API | REST API | Player props, game lines | 500 requests/month (free tier) |
| Supabase | Database | Storage, persistence | N/A |

### Installation

```bash
pip install nba_api requests supabase
```

### Authentication

```bash
# .env
ODDS_API_KEY=<your_odds_api_key>
SUPABASE_URL=<your_supabase_url>
SUPABASE_KEY=<your_supabase_key>
```

---

## 2. nba_api Endpoints

### 2.1 PlayerGameLog

**Purpose**: Player game-by-game statistics
**Signal Usage**: Trend, Line Value, Usage

```python
from nba_api.stats.endpoints import playergamelog

gamelog = playergamelog.PlayerGameLog(
    player_id=2544,  # LeBron James
    season='2024-25',
    season_type_all_star='Regular Season'
)
df = gamelog.get_data_frames()[0]
```

**Columns**:
| Column | Type | Description | Signal |
|--------|------|-------------|--------|
| `Player_ID` | int | NBA player ID | - |
| `GAME_DATE` | str | Date (e.g., "DEC 15, 2024") | Environment |
| `MATCHUP` | str | e.g., "LAL vs. DET" | - |
| `WL` | str | "W" or "L" | - |
| `MIN` | float | Minutes played | Usage |
| `PTS` | int | Points scored | Line Value, Trend |
| `REB` | int | Total rebounds | Line Value, Trend |
| `AST` | int | Assists | Line Value, Trend |
| `STL` | int | Steals | Line Value, Trend |
| `BLK` | int | Blocks | Line Value, Trend |
| `TOV` | int | Turnovers | Line Value, Trend |
| `FGM` | int | Field goals made | Line Value |
| `FGA` | int | Field goals attempted | Usage |
| `FG_PCT` | float | Field goal percentage | - |
| `FG3M` | int | Three-pointers made | Line Value, Trend |
| `FG3A` | int | Three-pointers attempted | Usage |
| `FTM` | int | Free throws made | Line Value |
| `FTA` | int | Free throws attempted | Usage |
| `PLUS_MINUS` | int | Plus/minus | - |

### 2.2 LeagueDashPlayerStats

**Purpose**: League-wide player statistics with advanced metrics
**Signal Usage**: Usage (USG_PCT), High-Value Filter

```python
from nba_api.stats.endpoints import leaguedashplayerstats

# Base stats
stats = leaguedashplayerstats.LeagueDashPlayerStats(
    season='2024-25',
    per_mode_detailed='PerGame'
)

# Advanced stats (for USG_PCT)
advanced = leaguedashplayerstats.LeagueDashPlayerStats(
    season='2024-25',
    per_mode_detailed='PerGame',
    measure_type_detailed_defense='Advanced'
)
```

**Key Columns (Advanced)**:
| Column | Type | Description | Signal |
|--------|------|-------------|--------|
| `PLAYER_ID` | int | NBA player ID | - |
| `PLAYER_NAME` | str | Full name | - |
| `TEAM_ID` | int | Team ID | - |
| `TEAM_ABBREVIATION` | str | e.g., "LAL" | - |
| `GP` | int | Games played | High-Value Filter |
| `MIN` | float | Minutes per game | High-Value Filter, Usage |
| `USG_PCT` | float | Usage percentage | High-Value Filter, Usage |
| `OFF_RATING` | float | Offensive rating | - |
| `DEF_RATING` | float | Defensive rating | Matchup |
| `PACE` | float | Pace factor | Matchup, Correlation |

### 2.3 LeagueDashTeamStats

**Purpose**: Team-level statistics
**Signal Usage**: Matchup (DEF_RATING), Correlation (PACE)

```python
from nba_api.stats.endpoints import leaguedashteamstats

stats = leaguedashteamstats.LeagueDashTeamStats(
    season='2024-25',
    per_mode_detailed='PerGame',
    measure_type_detailed_defense='Advanced'
)
```

**Key Columns**:
| Column | Type | Description | Signal |
|--------|------|-------------|--------|
| `TEAM_ID` | int | Team ID | - |
| `TEAM_NAME` | str | Full team name | - |
| `GP` | int | Games played | - |
| `W` | int | Wins | - |
| `L` | int | Losses | - |
| `DEF_RATING` | float | Points allowed per 100 possessions | Matchup |
| `PACE` | float | Possessions per 48 minutes | Matchup, Correlation |
| `OFF_RATING` | float | Points scored per 100 possessions | - |

### 2.4 TeamGameLog

**Purpose**: Team game schedule for B2B detection
**Signal Usage**: Environment (B2B, 3-in-4)

```python
from nba_api.stats.endpoints import teamgamelog

log = teamgamelog.TeamGameLog(
    team_id=1610612747,  # Lakers
    season='2024-25'
)
```

**Key Columns**:
| Column | Type | Description | Signal |
|--------|------|-------------|--------|
| `Game_ID` | str | NBA game ID | - |
| `GAME_DATE` | str | Date (e.g., "DEC 15, 2024") | Environment |
| `MATCHUP` | str | e.g., "LAL vs. DET" | - |
| `WL` | str | "W" or "L" | - |

**Derived Fields** (calculated in `data_provider.py`):
| Field | Calculation | Signal |
|-------|-------------|--------|
| `DAYS_REST` | Date difference to previous game | Environment |
| `IS_B2B` | `DAYS_REST <= 1` | Environment |
| `IS_3_IN_4` | 3+ games in 4-day window | Environment |

### 2.5 ScoreboardV2

**Purpose**: Today's games
**Signal Usage**: Game context

```python
from nba_api.stats.endpoints import scoreboardv2

scoreboard = scoreboardv2.ScoreboardV2(game_date='2024-12-15')
```

**Key Columns**:
| Column | Type | Description |
|--------|------|-------------|
| `GAME_ID` | str | NBA game ID |
| `HOME_TEAM_ID` | int | Home team ID |
| `VISITOR_TEAM_ID` | int | Away team ID |
| `GAME_STATUS_TEXT` | str | Game status |

### 2.6 Static Data

```python
from nba_api.stats.static import players, teams

# All active players
all_players = players.get_active_players()
# Returns: [{'id': 2544, 'full_name': 'LeBron James', ...}, ...]

# All teams
all_teams = teams.get_teams()
# Returns: [{'id': 1610612747, 'abbreviation': 'LAL', 'full_name': 'Los Angeles Lakers', ...}, ...]
```

---

## 3. Odds API Markets

### 3.1 API Configuration

```python
BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "basketball_nba"
```

### 3.2 Player Prop Markets

**Primary Markets**:
| Market Key | Stat Type | nba_api Column |
|------------|-----------|----------------|
| `player_points` | points | `PTS` |
| `player_rebounds` | rebounds | `REB` |
| `player_assists` | assists | `AST` |
| `player_threes` | threes | `FG3M` |
| `player_blocks` | blocks | `BLK` |
| `player_steals` | steals | `STL` |
| `player_turnovers` | turnovers | `TOV` |
| `player_field_goals` | fgm | `FGM` |
| `player_frees_made` | ftm | `FTM` |

**Combo Props**:
| Market Key | Stat Type | Calculation |
|------------|-----------|-------------|
| `player_points_rebounds_assists` | pra | `PTS + REB + AST` |
| `player_points_rebounds` | pr | `PTS + REB` |
| `player_points_assists` | pa | `PTS + AST` |
| `player_rebounds_assists` | ra | `REB + AST` |
| `player_blocks_steals` | blocks_steals | `BLK + STL` |

**Special Props**:
| Market Key | Stat Type | Notes |
|------------|-----------|-------|
| `player_double_double` | double_double | Binary - cannot calculate from history |
| `player_triple_double` | triple_double | Binary - cannot calculate from history |

**Alternate Markets** (same fields, alternate lines):
- `player_points_alternate`
- `player_rebounds_alternate`
- `player_assists_alternate`
- `player_threes_alternate`
- `player_blocks_alternate`
- `player_steals_alternate`

### 3.3 Game Markets

| Market Key | Description | Usage |
|------------|-------------|-------|
| `h2h` | Moneyline | - |
| `spreads` | Point spread | Environment (blowout risk) |
| `totals` | Over/under | Correlation |

### 3.4 API Response Structure

```json
{
  "id": "game_id_here",
  "sport_key": "basketball_nba",
  "home_team": "Los Angeles Lakers",
  "away_team": "Detroit Pistons",
  "commence_time": "2024-12-15T19:00:00Z",
  "bookmakers": [
    {
      "key": "draftkings",
      "markets": [
        {
          "key": "player_points",
          "outcomes": [
            {
              "name": "Over",
              "description": "LeBron James",
              "price": -115,
              "point": 24.5
            },
            {
              "name": "Under",
              "description": "LeBron James",
              "price": -105,
              "point": 24.5
            }
          ]
        }
      ]
    }
  ]
}
```

---

## 4. Internal Data Structures

### 4.1 PropContext (Signal Input)

```python
@dataclass
class PropContext:
    # Player identification
    player_id: int
    player_name: str
    team: str
    team_id: int

    # Prop details
    stat_type: str           # 'points', 'rebounds', 'assists', etc.
    line: float              # e.g., 24.5
    over_odds: int = -110    # American odds
    under_odds: int = -110

    # Season stats
    games_played: int = 0
    minutes_per_game: float = 0.0
    usage_pct: float = 0.0
    season_avg: float = 0.0  # Season average for stat_type

    # Recent stats (L5)
    recent_avg: float = 0.0
    recent_minutes: float = 0.0

    # Opponent context
    opponent_team: str = ''
    opponent_team_id: int = 0
    opponent_def_rating: float = 112.0  # League avg
    opponent_pace: float = 99.0         # League avg

    # Game context
    game_date: str = ''
    is_home: bool = True
    is_b2b: bool = False
    is_3_in_4: bool = False
    game_total: Optional[float] = None
    spread: Optional[float] = None

    # Flags
    is_high_value: bool = False
```

### 4.2 SignalResult (Signal Output)

```python
@dataclass
class SignalResult:
    signal_type: str         # 'line_value', 'trend', etc.
    strength: float          # -1.0 to +1.0 (negative=UNDER, positive=OVER)
    confidence: float        # 0.0 to 1.0
    evidence: str            # Human-readable explanation
    raw_data: Optional[Dict] # Underlying calculations
```

### 4.3 EdgeResult (Calculator Output)

```python
@dataclass
class EdgeResult:
    player_name: str
    stat_type: str
    line: float
    edge_score: float        # -1.0 to +1.0
    confidence: float        # 0.0 to 1.0
    direction: str           # 'over' or 'under'
    signals: List[SignalResult]
    recommendation: str      # 'strong_over', 'lean_over', 'pass', etc.
    expected_value: float
    is_high_value: bool
    over_odds: int
    under_odds: int
```

### 4.4 PlayerContext (Data Provider)

```python
@dataclass
class PlayerContext:
    player_id: int
    player_name: str
    team: str
    team_id: int

    # Season stats
    games_played: int
    minutes_per_game: float
    usage_pct: float

    # Per-game averages
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    fg3m: float
    fgm: float
    ftm: float
    tov: float

    # Recent form (L5)
    pts_l5: float
    reb_l5: float
    ast_l5: float
    min_l5: float

    # Flags
    is_high_value: bool
```

---

## 5. Field Mappings

### 5.1 Stat Type to nba_api Column

```python
STAT_TYPE_TO_FIELD = {
    'points': 'pts',
    'rebounds': 'reb',
    'assists': 'ast',
    'threes': 'fg3m',
    'blocks': 'blk',
    'steals': 'stl',
    'turnovers': 'tov',
    'fgm': 'fgm',
    'ftm': 'ftm',
    # Combo props
    'pra': ['pts', 'reb', 'ast'],
    'pr': ['pts', 'reb'],
    'pa': ['pts', 'ast'],
    'ra': ['reb', 'ast'],
    'blocks_steals': ['blk', 'stl'],
}
```

### 5.2 Odds API Market to Internal Stat Type

```python
MARKET_TO_STAT_TYPE = {
    'player_points': 'points',
    'player_rebounds': 'rebounds',
    'player_assists': 'assists',
    'player_threes': 'threes',
    'player_blocks': 'blocks',
    'player_steals': 'steals',
    'player_turnovers': 'turnovers',
    'player_field_goals': 'fgm',
    'player_frees_made': 'ftm',
    'player_points_rebounds_assists': 'pra',
    'player_points_rebounds': 'pr',
    'player_points_assists': 'pa',
    'player_rebounds_assists': 'ra',
    'player_blocks_steals': 'blocks_steals',
}
```

---

## 6. Caching Strategy

### 6.1 TTL by Data Type

```python
CACHE_TTL = {
    'player_gamelog': 3600,      # 1 hour (updates post-game)
    'league_stats': 3600,        # 1 hour
    'team_stats': 86400,         # 24 hours (changes slowly)
    'schedule': 3600,            # 1 hour
    'odds': 3600,                # 1 hour
}
```

### 6.2 Cache Keys

| Data Type | Key Pattern | Example |
|-----------|-------------|---------|
| Player Game Log | `gamelog_{player_id}_{season}` | `gamelog_2544_2024-25` |
| Team Stats | `team_stats_{season}` | `team_stats_2024-25` |
| High-Value Players | `high_value_{season}` | `high_value_2024-25` |
| Team Schedule | `schedule_{team_id}_{season}` | `schedule_1610612747_2024-25` |
| Today's Games | `games_{date}` | `games_2024-12-15` |
| Odds Events | `nba_events_{date}` | `nba_events_20241215` |
| Props | `props_{event_id}_...` | `props_abc123_player_points...` |

### 6.3 Odds API Cache Location

```
data/odds_cache/
├── nba_events_20241215.json
├── game_odds_abc123.json
└── props_abc123_player_points.json
```

---

## Appendix: Data Quality Notes

### nba_api Reliability

- **Rate Limiting**: 0.6s minimum between calls (unofficial)
- **Data Freshness**: Updates within hours of game completion
- **Coverage**: All NBA regular season and playoff games
- **Availability**: Generally stable, occasional timeouts

### Odds API Reliability

- **Rate Limiting**: 500 requests/month (free tier)
- **Data Freshness**: Real-time odds updates
- **Coverage**: Major sportsbooks (DraftKings, FanDuel, etc.)
- **Bookmaker Priority**: DraftKings > FanDuel > BetMGM

### Known Data Gaps

1. **Injuries**: nba_api does not provide injury data. Need external source.
2. **First Basket Props**: Cannot predict from historical data.
3. **Double/Triple Double**: Binary outcomes - cannot calculate probability from averages.
4. **Defensive Player Matchups**: Position-specific defense not available (unlike NFL).

---

*Document Version: 1.0*
*Last Updated: December 2025*
