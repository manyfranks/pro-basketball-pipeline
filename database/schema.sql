-- ============================================================================
-- NBA SGP Engine - Database Schema
-- ============================================================================
-- Run this in Supabase SQL Editor to create the NBA SGP tables.
-- Schema follows NHL pattern (most comprehensive).
--
-- Tables:
--   - nba_sgp_parlays: Parent parlay records
--   - nba_sgp_legs: Individual prop legs within parlays
--   - nba_sgp_settlements: Settlement records for parlays
-- ============================================================================


-- ============================================================================
-- Table: nba_sgp_parlays
-- Modeled after nhl_sgp_parlays (no week column, has season_type)
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

-- Indexes for parlays
CREATE INDEX IF NOT EXISTS idx_nba_sgp_parlays_date ON nba_sgp_parlays(game_date);
CREATE INDEX IF NOT EXISTS idx_nba_sgp_parlays_season ON nba_sgp_parlays(season, season_type);

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_nba_sgp_parlays_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_nba_sgp_parlays_updated_at ON nba_sgp_parlays;
CREATE TRIGGER trg_nba_sgp_parlays_updated_at
    BEFORE UPDATE ON nba_sgp_parlays
    FOR EACH ROW
    EXECUTE FUNCTION update_nba_sgp_parlays_updated_at();


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
    team VARCHAR(10),
    position VARCHAR(10),                 -- PG, SG, SF, PF, C

    -- Prop details
    stat_type VARCHAR(50) NOT NULL,       -- 'points', 'rebounds', 'assists', etc.
    line DECIMAL(10, 2),
    direction VARCHAR(10),                -- 'over' or 'under'
    odds INTEGER,                         -- American odds

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

-- Indexes for legs
CREATE INDEX IF NOT EXISTS idx_nba_sgp_legs_parlay ON nba_sgp_legs(parlay_id);
CREATE INDEX IF NOT EXISTS idx_nba_sgp_legs_player ON nba_sgp_legs(player_name);
CREATE INDEX IF NOT EXISTS idx_nba_sgp_legs_stat ON nba_sgp_legs(stat_type);
CREATE INDEX IF NOT EXISTS idx_nba_sgp_legs_result ON nba_sgp_legs(result);


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

-- Indexes for settlements
CREATE INDEX IF NOT EXISTS idx_nba_sgp_settlements_parlay ON nba_sgp_settlements(parlay_id);
CREATE INDEX IF NOT EXISTS idx_nba_sgp_settlements_result ON nba_sgp_settlements(result);


-- ============================================================================
-- Helpful Views
-- ============================================================================

-- View: Daily SGP Summary
-- Uses CTEs to avoid cartesian product between legs and settlements
CREATE OR REPLACE VIEW v_nba_sgp_daily_summary AS
WITH leg_stats AS (
    -- Aggregate leg-level stats per parlay
    SELECT
        l.parlay_id,
        COUNT(*) as total_legs,
        SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END) as legs_won,
        SUM(CASE WHEN l.result IN ('WIN', 'LOSS') THEN 1 ELSE 0 END) as legs_settled
    FROM nba_sgp_legs l
    GROUP BY l.parlay_id
),
parlay_data AS (
    -- Join parlays with pre-aggregated leg stats and settlements
    SELECT
        p.game_date,
        p.season,
        p.season_type,
        p.parlay_type,
        p.id as parlay_id,
        COALESCE(ls.total_legs, 0) as total_legs,
        COALESCE(ls.legs_won, 0) as legs_won,
        COALESCE(ls.legs_settled, 0) as legs_settled,
        s.result as parlay_result,
        s.profit
    FROM nba_sgp_parlays p
    LEFT JOIN leg_stats ls ON p.id = ls.parlay_id
    LEFT JOIN nba_sgp_settlements s ON p.id = s.parlay_id
)
SELECT
    game_date,
    season,
    season_type,
    parlay_type,
    COUNT(*) as total_parlays,
    SUM(total_legs) as total_legs,
    SUM(legs_won) as legs_hit,
    SUM(legs_settled) as legs_settled,
    COUNT(CASE WHEN parlay_result IS NOT NULL THEN 1 END) as parlays_settled,
    SUM(CASE WHEN parlay_result = 'WIN' THEN 1 ELSE 0 END) as parlays_won,
    COALESCE(SUM(profit), 0) as total_profit,
    ROUND(100.0 * SUM(CASE WHEN parlay_result = 'WIN' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(CASE WHEN parlay_result IS NOT NULL THEN 1 END), 0), 1) as parlay_win_rate,
    ROUND(100.0 * SUM(legs_won) / NULLIF(SUM(legs_settled), 0), 1) as leg_hit_rate
FROM parlay_data
GROUP BY game_date, season, season_type, parlay_type
ORDER BY game_date DESC, parlay_type;


-- View: Rolling Performance (7-day and 30-day windows)
CREATE OR REPLACE VIEW v_nba_sgp_rolling_performance AS
WITH leg_stats AS (
    SELECT
        l.parlay_id,
        COUNT(*) as total_legs,
        SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END) as legs_won,
        SUM(CASE WHEN l.result IN ('WIN', 'LOSS') THEN 1 ELSE 0 END) as legs_settled
    FROM nba_sgp_legs l
    GROUP BY l.parlay_id
),
parlay_data AS (
    SELECT
        p.id as parlay_id,
        p.game_date,
        p.parlay_type,
        COALESCE(ls.total_legs, 0) as total_legs,
        COALESCE(ls.legs_won, 0) as legs_won,
        COALESCE(ls.legs_settled, 0) as legs_settled,
        s.result as parlay_result
    FROM nba_sgp_parlays p
    LEFT JOIN leg_stats ls ON p.id = ls.parlay_id
    LEFT JOIN nba_sgp_settlements s ON p.id = s.parlay_id
    WHERE p.game_date >= CURRENT_DATE - INTERVAL '30 days'
)
SELECT
    parlay_type,
    -- 7-day metrics
    COUNT(CASE WHEN game_date >= CURRENT_DATE - INTERVAL '7 days' THEN 1 END) as parlays_7d,
    SUM(CASE WHEN game_date >= CURRENT_DATE - INTERVAL '7 days' THEN total_legs ELSE 0 END) as legs_7d,
    SUM(CASE WHEN game_date >= CURRENT_DATE - INTERVAL '7 days' THEN legs_won ELSE 0 END) as legs_hit_7d,
    SUM(CASE WHEN game_date >= CURRENT_DATE - INTERVAL '7 days' AND parlay_result = 'WIN' THEN 1 ELSE 0 END) as parlays_won_7d,
    ROUND(100.0 * SUM(CASE WHEN game_date >= CURRENT_DATE - INTERVAL '7 days' AND parlay_result = 'WIN' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(CASE WHEN game_date >= CURRENT_DATE - INTERVAL '7 days' AND parlay_result IS NOT NULL THEN 1 END), 0), 1) as parlay_win_rate_7d,
    ROUND(100.0 * SUM(CASE WHEN game_date >= CURRENT_DATE - INTERVAL '7 days' THEN legs_won ELSE 0 END)
          / NULLIF(SUM(CASE WHEN game_date >= CURRENT_DATE - INTERVAL '7 days' THEN legs_settled ELSE 0 END), 0), 1) as leg_hit_rate_7d,
    -- 30-day metrics
    COUNT(*) as parlays_30d,
    SUM(total_legs) as legs_30d,
    SUM(legs_won) as legs_hit_30d,
    SUM(CASE WHEN parlay_result = 'WIN' THEN 1 ELSE 0 END) as parlays_won_30d,
    ROUND(100.0 * SUM(CASE WHEN parlay_result = 'WIN' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(CASE WHEN parlay_result IS NOT NULL THEN 1 END), 0), 1) as parlay_win_rate_30d,
    ROUND(100.0 * SUM(legs_won) / NULLIF(SUM(legs_settled), 0), 1) as leg_hit_rate_30d
FROM parlay_data
GROUP BY parlay_type
ORDER BY parlay_type;


-- View: Season Summary (all-time by season)
CREATE OR REPLACE VIEW v_nba_sgp_season_summary AS
WITH leg_stats AS (
    SELECT
        l.parlay_id,
        COUNT(*) as total_legs,
        SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END) as legs_won,
        SUM(CASE WHEN l.result IN ('WIN', 'LOSS') THEN 1 ELSE 0 END) as legs_settled
    FROM nba_sgp_legs l
    GROUP BY l.parlay_id
),
parlay_data AS (
    SELECT
        p.season,
        p.season_type,
        p.game_date,
        p.id as parlay_id,
        COALESCE(ls.total_legs, 0) as total_legs,
        COALESCE(ls.legs_won, 0) as legs_won,
        COALESCE(ls.legs_settled, 0) as legs_settled,
        s.result as parlay_result,
        s.profit
    FROM nba_sgp_parlays p
    LEFT JOIN leg_stats ls ON p.id = ls.parlay_id
    LEFT JOIN nba_sgp_settlements s ON p.id = s.parlay_id
)
SELECT
    season,
    season_type,
    COUNT(*) as total_parlays,
    SUM(total_legs) as total_legs,
    SUM(legs_won) as total_legs_hit,
    SUM(legs_settled) as total_legs_settled,
    COUNT(CASE WHEN parlay_result IS NOT NULL THEN 1 END) as parlays_settled,
    SUM(CASE WHEN parlay_result = 'WIN' THEN 1 ELSE 0 END) as parlays_won,
    SUM(CASE WHEN parlay_result = 'LOSS' THEN 1 ELSE 0 END) as parlays_lost,
    COALESCE(SUM(profit), 0) as total_profit,
    ROUND(100.0 * SUM(CASE WHEN parlay_result = 'WIN' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(CASE WHEN parlay_result IS NOT NULL THEN 1 END), 0), 1) as parlay_win_rate,
    ROUND(100.0 * SUM(legs_won) / NULLIF(SUM(legs_settled), 0), 1) as leg_hit_rate,
    MIN(game_date) as first_game,
    MAX(game_date) as last_game
FROM parlay_data
GROUP BY season, season_type
ORDER BY season DESC, season_type;


-- View: Prop Type Performance (by stat_type)
CREATE OR REPLACE VIEW v_nba_sgp_prop_performance AS
SELECT
    l.stat_type,
    l.direction,
    COUNT(*) as total_picks,
    SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN l.result = 'LOSS' THEN 1 ELSE 0 END) as losses,
    SUM(CASE WHEN l.result IN ('PUSH', 'VOID') THEN 1 ELSE 0 END) as pushes_voids,
    SUM(CASE WHEN l.result IS NULL THEN 1 ELSE 0 END) as pending,
    ROUND(100.0 * SUM(CASE WHEN l.result = 'WIN' THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN l.result IN ('WIN', 'LOSS') THEN 1 ELSE 0 END), 0), 1) as win_rate,
    ROUND(AVG(l.edge_pct)::numeric, 2) as avg_edge,
    ROUND(AVG(l.confidence)::numeric, 3) as avg_confidence,
    ROUND(AVG(l.line)::numeric, 1) as avg_line
FROM nba_sgp_legs l
GROUP BY l.stat_type, l.direction
HAVING COUNT(*) >= 3
ORDER BY win_rate DESC NULLS LAST, total_picks DESC;


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
    ROUND(AVG(l.edge_pct)::numeric, 2) as avg_projected_edge
FROM nba_sgp_legs l
WHERE l.result IS NOT NULL AND l.result NOT IN ('VOID', 'PUSH')
GROUP BY l.player_name, l.team, l.stat_type
HAVING COUNT(*) >= 2
ORDER BY times_recommended DESC, win_rate DESC;


-- View: Recent Parlays with Legs (for dashboard)
CREATE OR REPLACE VIEW v_nba_sgp_recent_parlays AS
SELECT
    p.id as parlay_id,
    p.game_date,
    p.home_team,
    p.away_team,
    p.parlay_type,
    p.total_legs,
    p.combined_odds,
    p.thesis,
    p.season,
    p.season_type,
    s.result as settlement_result,
    s.legs_hit,
    s.profit,
    s.settled_at,
    COALESCE(
        json_agg(
            json_build_object(
                'player_name', l.player_name,
                'stat_type', l.stat_type,
                'line', l.line,
                'direction', l.direction,
                'odds', l.odds,
                'edge_pct', l.edge_pct,
                'result', l.result,
                'actual_value', l.actual_value
            ) ORDER BY l.leg_number
        ) FILTER (WHERE l.id IS NOT NULL),
        '[]'::json
    ) as legs
FROM nba_sgp_parlays p
LEFT JOIN nba_sgp_settlements s ON p.id = s.parlay_id
LEFT JOIN nba_sgp_legs l ON p.id = l.parlay_id
GROUP BY p.id, s.id
ORDER BY p.game_date DESC, p.created_at DESC
LIMIT 50;


-- ============================================================================
-- Enable Row Level Security (RLS) for public API access if needed
-- ============================================================================
-- Uncomment if using Supabase client from frontend

-- ALTER TABLE nba_sgp_parlays ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE nba_sgp_legs ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE nba_sgp_settlements ENABLE ROW LEVEL SECURITY;

-- CREATE POLICY "Allow read access" ON nba_sgp_parlays FOR SELECT USING (true);
-- CREATE POLICY "Allow read access" ON nba_sgp_legs FOR SELECT USING (true);
-- CREATE POLICY "Allow read access" ON nba_sgp_settlements FOR SELECT USING (true);


-- ============================================================================
-- Grant permissions (for service role)
-- ============================================================================
-- These should already be handled by Supabase, but included for completeness

-- GRANT ALL ON nba_sgp_parlays TO service_role;
-- GRANT ALL ON nba_sgp_legs TO service_role;
-- GRANT ALL ON nba_sgp_settlements TO service_role;
