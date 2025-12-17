# NBA SGP Engine - Orchestration Design

## Overview

This document outlines the orchestration architecture for the NBA SGP Engine, including:
- Pipeline stages and execution flow
- Season phase detection and handling
- Database schema design (aligned with NFL/NHL/NCAAF production)
- Scheduler configuration
- Settlement flow
- Timezone handling (critical)

---

## 1. Pipeline Architecture

### 1.1 Three-Stage Pipeline (MVP)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     NBA SGP DAILY ORCHESTRATOR                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  STAGE 1: SETTLEMENT (Morning Run - 7am PT / 10am ET)                       │
│  ├── Settle previous day's SGP parlays                                      │
│  ├── For each parlay: check if ALL legs hit                                 │
│  ├── Update leg results (WIN/LOSS/PUSH/VOID)                                │
│  ├── Create settlement record (parlay WIN/LOSS/VOID)                        │
│  └── Skip DNP players (mark leg as VOID, not LOSS)                          │
│                                                                              │
│  STAGE 2: SGP GENERATION (Two runs daily)                                   │
│  ├── RUN 1: 7am PT / 10am ET - Early predictions with overnight news        │
│  ├── RUN 2: 2pm ET - After injury report cutoff, final predictions          │
│  │                                                                           │
│  │   For each run:                                                          │
│  │   ├── Fetch today's games from Odds API                                  │
│  │   ├── Fetch player props for each game                                   │
│  │   ├── Check injury status via ESPN API                                   │
│  │   ├── Skip OUT players, flag GTD players                                 │
│  │   ├── Enrich with nba_api player context (stats, trends)                 │
│  │   ├── Run edge calculator (6 signals) on each prop                       │
│  │   ├── Select top props and build SGP parlays                             │
│  │   └── Save parlays + legs to database                                    │
│                                                                              │
│  STAGE 3: INSIGHTS (Optional - Future)                                      │
│  ├── Generate rule-based insights (hot streaks, trends)                     │
│  └── Generate LLM narrative (optional, via OpenRouter)                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Execution Modes

| Flag | Description |
|------|-------------|
| `--settle-only` | Run only Stage 1 (settlement) |
| `--generate-only` | Run only Stage 2 (skip settlement) |
| `--no-llm` | Skip LLM narrative generation |
| `--dry-run` | Don't write to database |
| `--force-refresh` | Ignore cache, refetch all data |
| `--date YYYY-MM-DD` | Target specific date (in ET) |
| `--season-type TYPE` | Override season detection (regular/playoffs/cup/playin) |

---

## 2. CRITICAL: Timezone Handling

### 2.1 The Problem

NBA operates on Eastern Time. Schedulers (Railway/cron) run in UTC. This causes bugs:
- A 7pm ET game on Dec 15 is actually 00:00 UTC on Dec 16
- Running "today's games" at 10am UTC (5am ET) may miss afternoon/evening games
- Settlement for "yesterday" in UTC may be wrong day in ET

### 2.2 The Solution

**All NBA operations use ET as canonical timezone:**

```python
from datetime import datetime, date
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
UTC = ZoneInfo('UTC')

def get_today_et() -> date:
    """Get today's date in Eastern Time."""
    return datetime.now(ET).date()

def get_yesterday_et() -> date:
    """Get yesterday's date in Eastern Time (for settlement)."""
    return (datetime.now(ET) - timedelta(days=1)).date()

# ALWAYS log timezone explicitly
logger.info(f"Processing games for {target_date} ET")
```

### 2.3 Scheduler Times

| Scheduler (UTC) | Eastern Time | Pacific Time | Purpose |
|-----------------|--------------|--------------|---------|
| 15:00 UTC | 10:00 AM ET | 7:00 AM PT | Morning: Settlement + Early SGP |
| 19:00 UTC | 2:00 PM ET | 11:00 AM PT | Afternoon: Final SGP (post injury cutoff) |

---

## 3. NBA Season Phases (2025-26 Season)

### 3.1 Season Calendar

```python
SEASON_CONFIG = {
    2026: {  # 2025-26 Season (use ending year as key)
        'preseason_start': date(2025, 10, 3),
        'regular_season_start': date(2025, 10, 21),
        'nba_cup_start': date(2025, 11, 11),
        'nba_cup_knockout': date(2025, 12, 9),
        'nba_cup_finals': date(2025, 12, 16),
        'christmas': date(2025, 12, 25),
        'mlk_day': date(2026, 1, 19),
        'allstar_start': date(2026, 2, 13),
        'allstar_end': date(2026, 2, 18),
        'regular_season_end': date(2026, 4, 12),
        'playin_start': date(2026, 4, 14),
        'playin_end': date(2026, 4, 17),
        'playoffs_start': date(2026, 4, 18),
        'finals_start': date(2026, 6, 4),
        'finals_end': date(2026, 6, 21),
    }
}

def get_season_phase(target_date: date) -> tuple[int, str]:
    """
    Determine the season year and phase for a given date.

    Returns:
        (season_year, phase) where phase is one of:
        - 'preseason': Skip processing
        - 'regular': Normal processing
        - 'nba_cup': Regular + NBA Cup context
        - 'allstar': Skip processing
        - 'playin': Playoff-style processing
        - 'playoffs': Playoff-style processing
        - 'offseason': Skip processing
    """
```

### 3.2 Phase-Specific Handling

| Phase | Pipeline Behavior |
|-------|-------------------|
| **Preseason** | Skip entirely - no predictions |
| **Regular Season** | Full pipeline, normal processing |
| **NBA Cup Games** | Full pipeline + flag `is_cup_game=True` |
| **Christmas/MLK** | Premium slate - run normally |
| **All-Star Break** | Skip entirely - no games |
| **Play-In Tournament** | Playoff mode |
| **Playoffs** | Enhanced signals - track series fatigue |
| **Off-Season** | Skip entirely - no games |

---

## 4. Database Schema

### 4.1 Production Schema Analysis

Queried actual production tables:

| Table | Row Count | Key Columns |
|-------|-----------|-------------|
| `nfl_sgp_parlays` | 4 | week, league (no season_type) |
| `nfl_sgp_legs` | 12 | Basic fields |
| `nhl_sgp_parlays` | 16 | season_type, updated_at (no week) |
| `nhl_sgp_legs` | 62 | **player_id, model_probability, market_probability, pipeline_score/confidence/rank** |
| `nhl_sgp_settlements` | 9 | profit field |
| `ncaaf_sgp_parlays` | 4 | week + season_type |

**NBA should follow NHL pattern** (most comprehensive, no week concept).

### 4.2 NBA Tables (Production-Aligned)

```sql
-- ============================================================================
-- Table: nba_sgp_parlays
-- Modeled after nhl_sgp_parlays (no week column)
-- ============================================================================
CREATE TABLE IF NOT EXISTS nba_sgp_parlays (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Parlay identification
    parlay_type VARCHAR(50) NOT NULL,     -- 'primary', 'theme_stack', 'value_play'
    game_id VARCHAR(100) NOT NULL,        -- Odds API event ID
    game_date DATE NOT NULL,              -- Game date in ET
    home_team VARCHAR(10) NOT NULL,
    away_team VARCHAR(10) NOT NULL,

    -- Game context
    game_slot VARCHAR(20),                -- 'AFTERNOON', 'EVENING', 'LATE'

    -- Parlay details
    total_legs INTEGER NOT NULL,
    combined_odds INTEGER,                -- e.g., +450
    implied_probability DECIMAL(10, 6),
    thesis TEXT,                          -- Narrative explanation

    -- Temporal
    season INTEGER NOT NULL,              -- e.g., 2026 for 2025-26 season
    season_type VARCHAR(20) DEFAULT 'regular',  -- 'regular', 'playoffs', 'cup', 'playin'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT unique_nba_sgp_parlay UNIQUE (season, season_type, parlay_type, game_id)
);

CREATE INDEX IF NOT EXISTS idx_nba_sgp_parlays_date ON nba_sgp_parlays(game_date);
CREATE INDEX IF NOT EXISTS idx_nba_sgp_parlays_season ON nba_sgp_parlays(season, season_type);


-- ============================================================================
-- Table: nba_sgp_legs
-- Modeled after nhl_sgp_legs (includes player_id, probabilities, pipeline context)
-- ============================================================================
CREATE TABLE IF NOT EXISTS nba_sgp_legs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parlay_id UUID NOT NULL REFERENCES nba_sgp_parlays(id) ON DELETE CASCADE,
    leg_number INTEGER NOT NULL,

    -- Player identification
    player_name VARCHAR(100) NOT NULL,
    player_id INTEGER,                    -- nba_api player_id (for settlement matching)
    team VARCHAR(10) NOT NULL,
    position VARCHAR(10),                 -- PG, SG, SF, PF, C

    -- Prop details
    stat_type VARCHAR(50) NOT NULL,       -- 'points', 'rebounds', 'assists', etc.
    line DECIMAL(10, 2) NOT NULL,
    direction VARCHAR(10) NOT NULL,       -- 'over' or 'under'
    odds INTEGER NOT NULL,                -- American odds

    -- Edge assessment (from edge calculator)
    edge_pct DECIMAL(10, 4),              -- Edge as percentage
    confidence DECIMAL(10, 4),            -- 0.0 to 1.0
    model_probability DECIMAL(6, 4),      -- Our model's win probability
    market_probability DECIMAL(6, 4),     -- Implied from odds

    -- Evidence
    primary_reason TEXT,
    supporting_reasons JSONB DEFAULT '[]',
    risk_factors JSONB DEFAULT '[]',

    -- Signal breakdown
    signals JSONB DEFAULT '{}',

    -- Pipeline context (from main edge calculator)
    pipeline_score DECIMAL(6, 2),         -- Edge score from calculator
    pipeline_confidence VARCHAR(20),      -- 'very_high', 'high', 'medium', 'low'
    pipeline_rank INTEGER,                -- Daily rank within game

    -- Settlement (filled after game)
    actual_value DECIMAL(10, 2),
    result VARCHAR(10),                   -- 'WIN', 'LOSS', 'PUSH', 'VOID'

    created_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT unique_nba_sgp_leg UNIQUE (parlay_id, leg_number)
);

CREATE INDEX IF NOT EXISTS idx_nba_sgp_legs_parlay ON nba_sgp_legs(parlay_id);
CREATE INDEX IF NOT EXISTS idx_nba_sgp_legs_player ON nba_sgp_legs(player_name);
CREATE INDEX IF NOT EXISTS idx_nba_sgp_legs_stat ON nba_sgp_legs(stat_type);


-- ============================================================================
-- Table: nba_sgp_settlements
-- Modeled after nhl_sgp_settlements (includes profit)
-- ============================================================================
CREATE TABLE IF NOT EXISTS nba_sgp_settlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parlay_id UUID NOT NULL REFERENCES nba_sgp_parlays(id) ON DELETE CASCADE,

    -- Results
    legs_hit INTEGER NOT NULL,
    total_legs INTEGER NOT NULL,
    result VARCHAR(10) NOT NULL,          -- 'WIN', 'LOSS', 'VOID'
    profit DECIMAL(10, 2),                -- At $100 stake

    -- Optional notes/learnings
    notes TEXT,

    settled_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT unique_nba_sgp_settlement UNIQUE (parlay_id)
);

CREATE INDEX IF NOT EXISTS idx_nba_sgp_settlements_parlay ON nba_sgp_settlements(parlay_id);


-- ============================================================================
-- Helpful Views
-- ============================================================================

-- View: Daily SGP Summary
CREATE OR REPLACE VIEW v_nba_sgp_daily_summary AS
SELECT
    p.game_date,
    p.season,
    p.season_type,
    p.parlay_type,
    COUNT(DISTINCT p.id) as parlays_generated,
    COUNT(DISTINCT s.id) as parlays_settled,
    SUM(CASE WHEN s.parlay_result = 'WIN' THEN 1 ELSE 0 END) as parlays_won,
    SUM(s.legs_hit) as total_legs_hit,
    SUM(s.total_legs) as total_legs,
    ROUND(100.0 * SUM(CASE WHEN s.parlay_result = 'WIN' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(DISTINCT s.id), 0), 1) as parlay_win_rate,
    ROUND(100.0 * SUM(s.legs_hit) / NULLIF(SUM(s.total_legs), 0), 1) as leg_hit_rate
FROM nba_sgp_parlays p
LEFT JOIN nba_sgp_settlements s ON p.id = s.parlay_id
GROUP BY p.game_date, p.season, p.season_type, p.parlay_type
ORDER BY p.game_date DESC, p.parlay_type;


-- View: Signal Performance
CREATE OR REPLACE VIEW v_nba_sgp_signal_performance AS
SELECT
    key as signal_type,
    COUNT(*) as total_legs,
    SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END) as wins,
    ROUND(100.0 * SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(*), 0), 1) as win_rate
FROM nba_sgp_legs l
CROSS JOIN LATERAL jsonb_each(l.signals)
WHERE l.result IS NOT NULL
  AND l.result NOT IN ('VOID', 'PUSH')
  AND l.signals IS NOT NULL
  AND l.signals != '{}'::jsonb
GROUP BY key
ORDER BY win_rate DESC;


-- View: Player Performance
CREATE OR REPLACE VIEW v_nba_sgp_player_performance AS
SELECT
    l.player_name,
    l.team,
    l.stat_type,
    COUNT(*) as times_recommended,
    SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN l.result = 'LOSS' THEN 1 ELSE 0 END) as losses,
    ROUND(100.0 * SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(*), 0), 1) as win_rate,
    ROUND(AVG(l.edge_pct), 2) as avg_projected_edge
FROM nba_sgp_legs l
WHERE l.result IS NOT NULL AND l.result NOT IN ('VOID', 'PUSH')
GROUP BY l.player_name, l.team, l.stat_type
HAVING COUNT(*) >= 2
ORDER BY times_recommended DESC, win_rate DESC;
```

---

## 5. Settlement Flow

### 5.1 Hit Rate Definitions

| Metric | Formula | Description |
|--------|---------|-------------|
| **Parlay Hit Rate** | parlays_won / parlays_settled | % of parlays where ALL legs hit |
| **Leg Hit Rate** | legs_won / legs_settled | % of individual legs that hit (for signal calibration) |

### 5.2 Settlement Logic

```python
def settle_parlay(parlay_id: str, box_scores: Dict) -> SettlementResult:
    """
    Settle a parlay against actual game results.

    For each leg:
    1. Find player's actual stats from box score
    2. Check if player played (minutes > 0)
    3. If DNP: result = 'VOID' (don't count as loss)
    4. If played: compare actual vs line
       - actual > line AND direction = 'over' → WIN
       - actual < line AND direction = 'under' → WIN
       - actual == line → PUSH
       - else → LOSS

    Parlay result:
    - All legs WIN → parlay WIN
    - Any leg LOSS → parlay LOSS
    - All legs VOID → parlay VOID
    - Mix of WIN/VOID → depends on book rules (usually WIN)
    """
```

### 5.3 DNP Handling

Players who don't play should NOT count as losses:

```python
def get_leg_result(leg: dict, player_stats: dict) -> str:
    """Determine leg outcome."""
    if player_stats is None or player_stats.get('minutes', 0) == 0:
        return 'VOID'  # Did not play

    actual = player_stats.get(leg['stat_type'], 0)
    line = leg['line']
    direction = leg['direction']

    if actual == line:
        return 'PUSH'
    elif direction == 'over':
        return 'WIN' if actual > line else 'LOSS'
    else:  # under
        return 'WIN' if actual < line else 'LOSS'
```

---

## 6. Scheduler Configuration

### 6.1 Railway Cron Jobs

```python
# scheduler/nba_scheduler.py

NBA_SCHEDULE = {
    # Morning run: Settlement + Early SGP
    'morning': {
        'cron': '0 15 * * *',  # 15:00 UTC = 10 AM ET = 7 AM PT
        'command': 'python -m scripts.nba_daily_orchestrator',
        'description': 'Settlement + Early SGP generation',
    },

    # Afternoon run: Final SGP (post injury reports)
    'afternoon': {
        'cron': '0 19 * * *',  # 19:00 UTC = 2 PM ET = 11 AM PT
        'command': 'python -m scripts.nba_daily_orchestrator --generate-only --force-refresh',
        'description': 'Final SGP after injury reports',
    },
}
```

### 6.2 Pipeline Execution Order

**Morning Run (7am PT / 10am ET):**
1. Settlement: Settle yesterday's parlays
2. SGP Generation: Early predictions for today

**Afternoon Run (2pm ET):**
1. SGP Generation: Final predictions with updated injury info
2. Uses `--force-refresh` to overwrite morning predictions
3. Skips settlement (already done in morning)

---

## 7. Edge Cases

### 7.1 NBA Cup (In-Season Tournament)

- Games embedded in regular season schedule
- Group stage games count toward regular season standings
- Knockout games (semifinals/finals) are separate
- Flag with `is_cup_game=True` for tracking
- Championship game at neutral site (Las Vegas)

### 7.2 Postponed Games

- If game postponed: mark all legs as VOID
- Parlay becomes VOID
- Will need to detect via Odds API or nba_api

### 7.3 Player Traded Mid-Game

- Rare but possible
- Use stats from the game they actually played
- If no stats recorded, treat as VOID

### 7.4 Back-to-Back Detection

```python
def get_schedule_context(player_id: int, game_date: date) -> dict:
    """Get fatigue context for a player."""
    return {
        'is_b2b': bool,           # Back-to-back game
        'is_3_in_4': bool,        # 3 games in 4 nights
        'days_rest': int,         # Days since last game
        'is_home': bool,          # Home game
    }
```

---

## 8. Data Flow Audit

Per the debugging playbook, trace what populates each table:

| Table | Writer | When |
|-------|--------|------|
| `nba_sgp_parlays` | `nba_daily_orchestrator.py` Stage 2 | Morning + Afternoon runs |
| `nba_sgp_legs` | `nba_daily_orchestrator.py` Stage 2 | Morning + Afternoon runs |
| `nba_sgp_settlements` | `nba_daily_orchestrator.py` Stage 1 | Morning run only |

**Settlement reads:**
- `nba_sgp_parlays` (find unsettled for yesterday)
- `nba_sgp_legs` (get legs to settle)
- External: nba_api box scores (actual stats)

---

## 9. CLI Reference

```bash
# Full pipeline (settlement + SGP generation)
python -m scripts.nba_daily_orchestrator

# Settlement only (morning)
python -m scripts.nba_daily_orchestrator --settle-only

# SGP generation only (afternoon, skip settlement)
python -m scripts.nba_daily_orchestrator --generate-only

# Force refresh (afternoon run - overwrite morning predictions)
python -m scripts.nba_daily_orchestrator --generate-only --force-refresh

# Specific date (in ET)
python -m scripts.nba_daily_orchestrator --date 2025-12-16

# Dry run (no database writes)
python -m scripts.nba_daily_orchestrator --dry-run

# Override season type
python -m scripts.nba_daily_orchestrator --season-type playoffs
```

---

## 10. Implementation Phases

### Phase 1: MVP (Current Focus)
- [x] Database manager stub (parlays/legs/settlements) - `src/db_manager.py`
- [x] Orchestration script skeleton - `scripts/nba_daily_orchestrator.py`
- [x] Timezone handling module - Integrated in orchestrator (ET canonical)
- [x] Scheduler configuration - `scheduler/config.py`
- [ ] SGP generation (using existing edge calculator) - Stubbed, needs Odds API integration
- [ ] Settlement stub - Stubbed, needs box score integration

### Phase 2: Production
- [ ] Create database tables in Supabase (run `database/schema.sql`)
- [ ] Full Odds API integration for game fetching
- [ ] Settlement implementation with nba_api box scores
- [ ] Scheduler deployment (Railway)
- [ ] Monitoring/alerts

### Phase 3: Enhancements
- [ ] LLM insights
- [ ] Performance dashboard
- [ ] Backtesting framework

---

## 11. Files Created

| File | Description |
|------|-------------|
| `src/db_manager.py` | Supabase database manager for parlays/legs/settlements |
| `scripts/nba_daily_orchestrator.py` | Main daily pipeline orchestrator |
| `scheduler/config.py` | Cron schedule configuration |
| `database/schema.sql` | SQL schema for Supabase tables |
| `scripts/test_db_manager.py` | Database manager test script |

---

*Document Version: 3.0*
*Last Updated: December 2025*
