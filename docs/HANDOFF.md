# NBA SGP Engine - Developer Handoff

**Date**: December 17, 2025
**Version**: 1.0.0
**Status**: Production-Ready

---

## Quick Start

### What This Project Does

The NBA SGP Engine generates daily Same Game Parlay (SGP) recommendations for NBA games using a signal-based edge detection system. It:

1. Fetches player prop lines from The Odds API
2. Enriches with player stats from nba_api
3. Checks injury status via ESPN
4. Calculates edges using 6 weighted signals
5. Generates 3-leg parlays per game
6. Settles against actual box scores
7. Stores everything in Supabase

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Railway (Cron Job)                       │
│                     10:00 AM ET Daily                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           nba_daily_orchestrator.py                   │  │
│  │                                                        │  │
│  │   Stage 1: Settlement (yesterday)                     │  │
│  │   Stage 2: SGP Generation (today)                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│     ┌─────────────────────┼─────────────────────┐           │
│     ▼                     ▼                     ▼           │
│  ┌───────┐         ┌───────────┐         ┌──────────┐      │
│  │ Odds  │         │   Edge    │         │ Thesis   │      │
│  │ API   │         │Calculator │         │Generator │      │
│  └───────┘         └───────────┘         └──────────┘      │
│                           │                     │            │
│                     6 Signals:            OpenRouter         │
│                     - line_value          (Gemini 2.0)       │
│                     - trend                                  │
│                     - correlation                            │
│                     - matchup                                │
│                     - usage                                  │
│                     - environment                            │
│                           │                                  │
│                           ▼                                  │
│              ┌─────────────────────┐                        │
│              │      Supabase       │                        │
│              │    (PostgreSQL)     │                        │
│              └─────────────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Environment Variables

### Backend (Railway)

```bash
# Required
SUPABASE_URL=https://njpxyhacwepyxrlargpu.supabase.co
SUPABASE_KEY=<service_role_key>  # From Supabase dashboard
ODDS_API_KEY=<api_key>           # From the-odds-api.com

# Optional
OPENROUTER_API_KEY=<api_key>     # For LLM thesis generation
OPENROUTER_MODEL_NAME=google/gemini-2.0-flash-001  # Default
```

### Frontend

```bash
NEXT_PUBLIC_SUPABASE_URL=https://njpxyhacwepyxrlargpu.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon_key>  # From Supabase dashboard
```

---

## Database Schema

### Tables

| Table | Description | Key Columns |
|-------|-------------|-------------|
| `nba_sgp_parlays` | Parlay records | id, game_date, home_team, away_team, thesis |
| `nba_sgp_legs` | Individual props | parlay_id, player_name, stat_type, line, direction |
| `nba_sgp_settlements` | Results | parlay_id, legs_hit, result, profit |

### Views (Pre-built Queries)

| View | Description |
|------|-------------|
| `v_nba_sgp_daily_summary` | Daily win rates and profit |
| `v_nba_sgp_signal_performance` | Signal accuracy breakdown |
| `v_nba_sgp_player_performance` | Player-level hit rates |

### Example Queries

```sql
-- Today's parlays with legs
SELECT p.*, json_agg(l.*) as legs
FROM nba_sgp_parlays p
LEFT JOIN nba_sgp_legs l ON l.parlay_id = p.id
WHERE p.game_date = CURRENT_DATE
GROUP BY p.id;

-- Performance last 7 days
SELECT * FROM v_nba_sgp_daily_summary
WHERE game_date >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY game_date DESC;

-- Unsettled parlays
SELECT p.* FROM nba_sgp_parlays p
LEFT JOIN nba_sgp_settlements s ON s.parlay_id = p.id
WHERE s.id IS NULL AND p.game_date < CURRENT_DATE;
```

---

## Frontend Integration

### Supabase Client Setup

```typescript
// lib/supabase.ts
import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)
```

### Fetch Today's Parlays

```typescript
const { data: parlays, error } = await supabase
  .from('nba_sgp_parlays')
  .select(`
    *,
    nba_sgp_legs (*),
    nba_sgp_settlements (*)
  `)
  .eq('game_date', format(new Date(), 'yyyy-MM-dd'))
  .order('created_at', { ascending: false })
```

### Real-time Settlement Updates

```typescript
supabase
  .channel('settlements')
  .on('postgres_changes', {
    event: 'INSERT',
    schema: 'public',
    table: 'nba_sgp_settlements'
  }, (payload) => {
    // Handle new settlement
    console.log('Parlay settled:', payload.new)
  })
  .subscribe()
```

---

## Pipeline Schedule

| Time (ET) | UTC | Action |
|-----------|-----|--------|
| 10:00 AM | 15:00 | Settlement (yesterday) + SGP Generation (today) |

- Single daily run handles both settlement and generation
- Configured as Railway cron job: `0 15 * * *`
- Data does NOT update in real-time during games

---

## Performance Metrics (Backtested)

| Metric | Value | Notes |
|--------|-------|-------|
| **Parlays Tested** | 252 | Nov 2024 - Dec 2025 |
| **Leg Hit Rate** | 60.0% | Statistically significant |
| **Parlay Win Rate** | 45.9% | All 3 legs must hit |
| **Total Profit** | $35,390 | At $100/parlay |
| **ROI** | 151.9% | Excellent |
| **95% CI (Legs)** | 56.3% - 63.6% | Tight confidence interval |
| **Void Rate** | 8.8% | Mostly DNPs |

### By Stat Type

| Stat | Hit Rate | Assessment |
|------|----------|------------|
| Points | 65.0% | Best performer |
| Threes | 66.7% | Small sample |
| Assists | 61.0% | Solid |
| Rebounds | 51.2% | Weakest |

---

## Key Files

### Pipeline

| File | Description |
|------|-------------|
| `scripts/nba_daily_orchestrator.py` | Main entry point (Railway runs this) |
| `src/edge_calculator.py` | Signal-based edge detection |
| `src/settlement.py` | Settles parlays against box scores |
| `src/odds_client.py` | The Odds API integration |
| `src/data_provider.py` | nba_api integration |
| `src/injury_checker.py` | ESPN injury scraping |
| `src/thesis_generator.py` | LLM narrative generation |
| `src/db_manager.py` | Supabase operations |

### Configuration

| File | Description |
|------|-------------|
| `Dockerfile` | Production container |
| `railway.toml` | Railway deployment config |
| `requirements.txt` | Python dependencies |

### Documentation

| File | Description |
|------|-------------|
| `docs/API_SPEC.md` | Data access patterns |
| `docs/FRONTEND_SPEC.md` | UI/UX specifications |
| `docs/ORCHESTRATION_DESIGN.md` | Pipeline architecture |
| `docs/PRODUCTION_READINESS.md` | Deployment guide |

---

## Common Issues

### "Player not found" warnings
- Some players have inconsistent naming between Odds API and nba_api
- Non-blocking: parlay generation continues with other players
- Examples: "Vincent Williams Jr" vs "Vince Williams Jr"

### Void legs
- Player DNP (Did Not Play) = leg is VOID, not LOSS
- If any leg is VOID, entire parlay is typically VOID
- Historical void rate: ~8.8%

### Timezone confusion
- All dates are in **Eastern Time (ET)**
- Pipeline runs at 10 AM ET (15:00 UTC)
- NBA games are displayed in ET

---

## Running Locally

```bash
# Clone and setup
git clone <repo>
cd pro-basketball-pipeline
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your keys

# Run pipeline manually
python -m scripts.nba_daily_orchestrator --dry-run

# Run for specific date
python -m scripts.nba_daily_orchestrator --date 2025-12-16 --dry-run
```

---

## Monitoring

### Daily Checks
- [ ] Cron job completed successfully (Railway logs)
- [ ] Parlays generated for today's games
- [ ] Yesterday's parlays settled

### Weekly Metrics
- [ ] Win rate trending (target: >55% legs)
- [ ] Void rate normal (<15%)
- [ ] No database errors

### Alerts to Configure
1. Cron job failure notification
2. No parlays generated when games exist
3. Settlement errors

---

## Contact

For questions about this codebase, refer to:
- `docs/` folder for detailed specifications
- Git history for implementation decisions
- Railway dashboard for deployment logs

---

*Last Updated: December 17, 2025*
