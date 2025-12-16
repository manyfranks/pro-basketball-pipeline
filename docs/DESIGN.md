# NBA SGP Engine - Design Document

**Version:** 1.0 (POC)
**Last Updated:** December 2025
**Status:** Path B Implementation (No Pipeline)

---

## Executive Summary

The NBA SGP Engine applies the **market-first, edge-detection philosophy** from the NFL/NHL SGP engines to NBA player props. We use `nba_api` for player statistics and compare against Odds API lines to find systematic edges.

**Architecture Decision**: Following the NHL SGP dual-path pattern, we're implementing **Path B** (direct API, no pipeline enrichment) as our POC. This is validated by NHL backtesting showing Path B achieves ~50% baseline, with potential for 52-55% with good signal tuning.

**Key Advantage**: Unlike NHL API, `nba_api` provides rich derived metrics (usage rate, advanced stats) that give us "free" pipeline-like intelligence.

---

## 1. Data Provider: nba_api

### 1.1 Installation
```bash
pip install nba_api
```

### 1.2 Key Endpoints

| Endpoint | Purpose | SGP Signal |
|----------|---------|------------|
| `playergamelog.PlayerGameLog` | Player game-by-game stats | Trend, Usage |
| `leaguedashplayerstats.LeagueDashPlayerStats` | League-wide stats, rankings | Matchup, Usage |
| `teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits` | Team defensive stats | Matchup |
| `scoreboardv2.ScoreboardV2` | Today's games | Environment |
| `players.get_active_players()` | Player ID lookup | Utility |
| `teams.get_teams()` | Team ID lookup | Utility |

### 1.3 Player Game Log Schema

```python
# From playergamelog.PlayerGameLog
COLUMNS = [
    'SEASON_ID', 'Player_ID', 'Game_ID', 'GAME_DATE', 'MATCHUP', 'WL',
    'MIN',           # Minutes played
    'FGM', 'FGA', 'FG_PCT',     # Field goals
    'FG3M', 'FG3A', 'FG3_PCT',  # 3-pointers
    'FTM', 'FTA', 'FT_PCT',     # Free throws
    'OREB', 'DREB', 'REB',      # Rebounds
    'AST',           # Assists
    'STL',           # Steals
    'BLK',           # Blocks
    'TOV',           # Turnovers
    'PF',            # Personal fouls
    'PTS',           # Points
    'PLUS_MINUS'     # Plus/minus
]
```

---

## 2. Odds API → nba_api Mapping

### 2.1 Primary Props

| Odds API Market Key | nba_api Column | Notes |
|---------------------|----------------|-------|
| `player_points` | `PTS` | Direct mapping |
| `player_rebounds` | `REB` | Direct mapping |
| `player_assists` | `AST` | Direct mapping |
| `player_threes` | `FG3M` | Direct mapping |
| `player_blocks` | `BLK` | Direct mapping |
| `player_steals` | `STL` | Direct mapping |
| `player_turnovers` | `TOV` | Direct mapping |
| `player_field_goals` | `FGM` | Direct mapping |
| `player_frees_made` | `FTM` | Direct mapping |

### 2.2 Combo Props

| Odds API Market Key | nba_api Calculation | Notes |
|---------------------|---------------------|-------|
| `player_points_rebounds_assists` | `PTS + REB + AST` | PRA |
| `player_points_rebounds` | `PTS + REB` | |
| `player_points_assists` | `PTS + AST` | |
| `player_rebounds_assists` | `REB + AST` | |
| `player_blocks_steals` | `BLK + STL` | Stocks |

### 2.3 Special Props

| Odds API Market Key | nba_api Calculation | Notes |
|---------------------|---------------------|-------|
| `player_double_double` | 2+ of (PTS≥10, REB≥10, AST≥10, STL≥10, BLK≥10) | Boolean |
| `player_triple_double` | 3+ of above | Boolean |
| `player_first_basket` | N/A | Cannot predict from historical |

---

## 3. Architecture (Path B)

### 3.1 Why Path B?

Per NHL SGP learnings, we have two architecture options:

| Path | Description | Expected Hit Rate |
|------|-------------|-------------------|
| **A** | Pipeline enrichment + Odds | 60-65% (validated in NHL) |
| **B** | Direct API + Odds | 50-55% baseline |

We're starting with **Path B** because:
1. No existing NBA pipeline to leverage
2. `nba_api` provides richer data than NHL API (usage rate, etc.)
3. Faster POC - validate before investing in pipeline build

### 3.2 Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     NBA SGP ENGINE (Path B)                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Odds API → nba_api Direct → 6 Signals → Edge Calculation       │
│             ↑                                                    │
│             │ PlayerGameLog (trend, usage)                       │
│             │ LeagueDashPlayerStats (rankings, USG_PCT)          │
│             │ TeamDashboard (opponent defense)                   │
│             │ ScoreboardV2 (B2B detection)                       │
│             │                                                    │
│             └── nba_api provides "free" derived intelligence     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 Component Structure

```
nba_engine/
├── docs/
│   ├── DESIGN.md              # This document
│   └── the_odds_api_docs.md   # Odds API reference
├── exploration/
│   └── explore_nba_api.py     # Data exploration script
├── src/
│   ├── __init__.py
│   ├── data_provider.py       # NBADataProvider (nba_api wrapper)
│   ├── odds_client.py         # Odds API integration
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── base.py            # BaseSignal, SignalResult
│   │   ├── line_value_signal.py
│   │   ├── trend_signal.py
│   │   ├── usage_signal.py
│   │   ├── matchup_signal.py
│   │   ├── environment_signal.py
│   │   └── correlation_signal.py
│   ├── edge_calculator.py     # Signal combination
│   └── sgp_builder.py         # Parlay construction
├── scripts/
│   ├── run_daily.py           # Daily SGP generation
│   ├── backtest.py            # Historical validation
│   └── settle.py              # Settlement
└── migrations/
    └── (uses existing nfl_sgp_* tables with league='NBA')
```

---

## 4. Signal Framework (Adapted from NHL)

### 4.1 Signal Weights (NBA-Tuned)

| Signal | NHL Weight | NBA Weight | Rationale |
|--------|------------|------------|-----------|
| Line Value | 35% | **30%** | Season avg vs line, slightly less predictive in NBA |
| Trend | 15% | **20%** | More games = more reliable trends |
| Usage | 10% | **20%** | Minutes/usage rate highly predictive in NBA |
| Matchup | 15% | **15%** | Opponent defensive rating |
| Environment | 15% | **10%** | B2B matters but less than NHL |
| Correlation | 10% | **5%** | Game totals less impactful (NBA is high-scoring) |

### 4.2 Trend Signal

**Data Source**: `PlayerGameLog` (last 5 games vs season)

```python
def calculate_trend(player_id: int, stat_type: str, line: float) -> SignalResult:
    """
    Compare player's last 5 games vs season average.

    Example:
    - LeBron L5 PTS: 23.0
    - LeBron Season PTS: 24.4
    - Trend: -5.8% (UNDER signal)
    """
    gamelog = PlayerGameLog(player_id=player_id, season='2024-25')
    df = gamelog.get_data_frames()[0]

    l5_avg = df.head(5)[stat_type].mean()
    season_avg = df[stat_type].mean()

    pct_diff = (l5_avg - season_avg) / season_avg

    # Positive = OVER, Negative = UNDER
    strength = max(-1.0, min(1.0, pct_diff * 2))  # Scale to -1 to 1

    return SignalResult(
        signal_type='trend',
        strength=strength,
        confidence=calculate_confidence(len(df), variance(df[stat_type])),
        evidence=f"L5 avg {l5_avg:.1f} vs season {season_avg:.1f} ({pct_diff:+.1%})"
    )
```

### 3.2 Usage Signal

**Data Source**: `PlayerGameLog` (minutes, attempts trending)

```python
def calculate_usage(player_id: int, stat_type: str) -> SignalResult:
    """
    Track opportunity metrics:
    - Minutes trending up/down
    - Shot attempts (FGA) for points
    - Minutes * usage rate
    """
    # If minutes trending down, reduce confidence in OVER bets
    # If minutes trending up, increase confidence in OVER bets
```

**Key Usage Metrics by Prop Type**:

| Prop | Primary Usage Metric | Secondary |
|------|----------------------|-----------|
| Points | FGA, FTA, MIN | USG_PCT |
| Rebounds | MIN, OREB+DREB | Team pace |
| Assists | MIN, Touches | Team pace |
| Threes | FG3A | MIN |
| Blocks/Steals | MIN | Defensive rating |

### 3.3 Matchup Signal

**Data Source**: `LeagueDashPlayerStats` + opponent defensive ratings

```python
def calculate_matchup(player_id: int, stat_type: str, opponent_team: str) -> SignalResult:
    """
    Compare opponent's defense vs league average.

    Example:
    - OKC allows 108.5 PPG (2nd best in league)
    - League average: 114.2 PPG
    - Signal: UNDER (-5.0% vs league)
    """
```

**Matchup Factors**:

| Prop | Matchup Factor |
|------|----------------|
| Points | Opponent DRTG (defensive rating) |
| Rebounds | Opponent REB rate, pace |
| Assists | Opponent TOV rate (force turnovers = fewer assists) |
| Threes | Opponent 3PT defense |

### 3.4 Environment Signal

**Data Source**: `ScoreboardV2` + schedule analysis

```python
def calculate_environment(player_id: int, game_date: str) -> SignalResult:
    """
    Check situational factors:
    - Back-to-back games (B2B) → reduced minutes/performance
    - Home vs away
    - Rest days (3+ days rest → bump?)
    - Altitude (Denver)
    """
```

**Environment Impact Matrix**:

| Factor | Impact | Direction |
|--------|--------|-----------|
| 2nd game of B2B | -5 to -10% | UNDER |
| 3+ days rest | +2 to +5% | OVER |
| Road game | -2 to -3% | UNDER |
| Denver (altitude) | -3 to -5% | UNDER |

### 3.5 Correlation Signal

**Data Source**: Odds API (game total, spread)

```python
def calculate_correlation(stat_type: str, game_total: float, spread: float) -> SignalResult:
    """
    Higher game total → more possessions → more counting stats
    Large spread → potential garbage time / blowout risk
    """
```

**Correlation Matrix**:

| Game Total | Impact on Props |
|------------|-----------------|
| > 230 | +5-8% scoring props |
| < 210 | -5-8% scoring props |
| 215-225 | Neutral |

| Spread | Impact |
|--------|--------|
| > 10 pts | Garbage time risk, star benched early |
| < 5 pts | Full minutes likely |

---

## 4. NBA-Specific Considerations

### 4.1 Sample Size (vs NFL)

| Aspect | NFL | NBA |
|--------|-----|-----|
| Games per season | 17 | 82 |
| Games for trend (L3/L5) | 18% of season | 6% of season |
| Statistical stability | Lower | Higher |
| Recommended lookback | 3 games | 5-10 games |

**Implication**: NBA trends are more reliable due to larger sample size.

### 4.2 Back-to-Back Games

NBA has frequent B2Bs. This is a strong environmental signal:
- Minutes typically reduced 2-5 minutes
- Efficiency drops ~3-5%
- **Strong UNDER signal for 2nd game of B2B**

### 4.3 Load Management

Star players may rest on B2Bs or for minor injuries. Check:
- Injury reports (need separate data source)
- Recent minutes patterns
- Team's B2B policy

### 4.4 Blowout Risk

NBA has more blowouts than NFL. Large spreads (>10 pts) mean:
- Star may be benched in 4th quarter
- Props may not hit even if player is "on pace"
- **Reduce confidence on OVER props when spread > 10**

---

## 5. Implementation Phases

### Phase 1: Data Provider (Week 1)
- [ ] Create `NBADataProvider` class
- [ ] Implement player lookup by name
- [ ] Implement game log fetching with caching
- [ ] Handle rate limiting (0.6s between calls)

### Phase 2: Signal Implementations (Week 2)
- [ ] Trend signal (L5 vs season)
- [ ] Usage signal (minutes, attempts)
- [ ] Matchup signal (opponent defense)
- [ ] Environment signal (B2B detection)
- [ ] Correlation signal (from Odds API)

### Phase 3: SGP Engine (Week 3)
- [ ] Edge aggregator for NBA
- [ ] Parlay builder with correlation logic
- [ ] Database loader (use existing schema with `league='NBA'`)

### Phase 4: Integration (Week 4)
- [ ] Add to scheduler
- [ ] Unified landing page support
- [ ] Testing with live games

---

## 6. Database Schema

Use existing `nfl_sgp_parlays` table with `league` field:

```sql
-- Already added via migration
ALTER TABLE nfl_sgp_parlays ADD COLUMN league VARCHAR(10) NOT NULL DEFAULT 'NFL';

-- Query NBA parlays
SELECT * FROM nfl_sgp_parlays WHERE league = 'NBA' AND game_date = CURRENT_DATE;
```

**Note**: Consider renaming table to `sgp_parlays` (drop `nfl_` prefix) when multi-league is fully implemented.

---

## 7. Rate Limiting

nba_api has unofficial rate limits. Implement:

```python
import time

class RateLimiter:
    def __init__(self, min_interval: float = 0.6):
        self.min_interval = min_interval
        self.last_call = 0

    def wait(self):
        elapsed = time.time() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()
```

---

## 8. Caching Strategy

NBA data changes less frequently than NFL. Implement:

```python
CACHE_TTL = {
    'player_gamelog': 3600,      # 1 hour (updates post-game)
    'league_stats': 3600,        # 1 hour
    'team_defense': 86400,       # 24 hours
    'schedule': 3600,            # 1 hour
}
```

---

*Document Version: 1.0*
*Last Updated: December 2025*
