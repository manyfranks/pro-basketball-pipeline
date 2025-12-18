# NBA SGP Engine - API Specification

**Version**: 1.0
**Base URL**: `/api/v1`
**Authentication**: Bearer token (header: `Authorization: Bearer <token>`)

---

## Overview

This document specifies the data access patterns for the NBA SGP Engine frontend integration.

---

## Data Access Options

### Option A: Direct Supabase (Recommended for MVP)

The simplest approach is querying Supabase directly using the `supabase-js` client. No backend API server required.

**Environment Variables:**
```
NEXT_PUBLIC_SUPABASE_URL=https://njpxyhacwepyxrlargpu.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<from Supabase dashboard>
```

**Setup:**
```typescript
// lib/supabase.ts
import { createClient } from '@supabase/supabase-js'

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)
```

**Example Queries:**
```typescript
// Today's parlays with legs and settlements
const { data: parlays } = await supabase
  .from('nba_sgp_parlays')
  .select(`
    *,
    nba_sgp_legs (*),
    nba_sgp_settlements (*)
  `)
  .eq('game_date', '2025-12-17')
  .order('created_at', { ascending: false })

// Performance summary (last 30 days)
const { data: performance } = await supabase
  .from('v_nba_sgp_daily_summary')
  .select('*')
  .order('game_date', { ascending: false })
  .limit(30)

// Player history
const { data: playerLegs } = await supabase
  .from('nba_sgp_legs')
  .select('*, nba_sgp_parlays!inner(game_date)')
  .ilike('player_name', '%LeBron%')
  .order('created_at', { ascending: false })
```

**Real-time Updates (Supabase Realtime):**
```typescript
// Subscribe to new settlements
supabase
  .channel('nba-settlements')
  .on('postgres_changes', {
    event: 'INSERT',
    schema: 'public',
    table: 'nba_sgp_settlements'
  }, (payload) => {
    console.log('New settlement:', payload.new)
  })
  .subscribe()
```

### Option B: REST API (Future Enhancement)

If you need custom business logic, rate limiting, or caching, implement a REST API server. The endpoints below describe this approach.

**Base URL**: `/api/v1`
**Authentication**: Bearer token (header: `Authorization: Bearer <token>`)

---

## Data Models

### Parlay

```typescript
interface Parlay {
  id: string;                    // UUID
  parlayType: string;            // 'primary', 'value_play', 'theme_stack'
  gameId: string;                // Odds API event ID
  gameDate: string;              // YYYY-MM-DD
  homeTeam: string;              // Team abbreviation (e.g., 'LAL')
  awayTeam: string;              // Team abbreviation (e.g., 'BOS')
  gameSlot: string;              // 'AFTERNOON', 'EVENING', 'LATE'
  totalLegs: number;             // Number of legs (typically 3)
  combinedOdds: number;          // American odds (e.g., +450)
  impliedProbability: number;    // 0.0 to 1.0
  thesis: string;                // Narrative explanation
  season: number;                // e.g., 2026 for 2025-26 season
  seasonType: string;            // 'regular', 'playoffs', 'cup', 'playin'
  createdAt: string;             // ISO timestamp

  // Nested data
  legs: Leg[];
  settlement?: Settlement;
}
```

### Leg

```typescript
interface Leg {
  id: string;                    // UUID
  legNumber: number;             // 1, 2, 3
  playerName: string;            // e.g., 'LeBron James'
  playerId: number | null;       // NBA player ID
  team: string;                  // Team abbreviation
  position: string | null;       // 'G', 'F', 'C' (may be null)
  statType: string;              // 'points', 'assists', 'rebounds', etc.
  line: number;                  // e.g., 24.5
  direction: string;             // 'over', 'under'
  odds: number;                  // American odds (e.g., -115)
  edgePct: number;               // Signal strength (-100 to +100)
  confidence: number;            // 0.0 to 1.0
  modelProbability: number;      // Our estimated probability
  marketProbability: number;     // Implied from odds
  primaryReason: string;         // Main thesis for this leg
  supportingReasons: string[];   // Additional factors
  riskFactors: string[];         // Potential concerns
  signals: SignalBreakdown;      // Individual signal scores

  // Settlement data (after game)
  actualValue: number | null;
  result: 'WIN' | 'LOSS' | 'PUSH' | 'VOID' | null;
}
```

### SignalBreakdown

```typescript
interface SignalBreakdown {
  line_value: number;     // -1.0 to +1.0
  trend: number;
  correlation: number;
  matchup: number;
  usage: number;
  environment: number;
}
```

### Settlement

```typescript
interface Settlement {
  id: string;
  parlayId: string;
  legsHit: number;
  totalLegs: number;
  result: 'WIN' | 'LOSS' | 'VOID';
  profit: number;          // At $100 stake
  settledAt: string;       // ISO timestamp
}
```

### Performance

```typescript
interface Performance {
  totalParlays: number;
  wins: number;
  losses: number;
  voids: number;
  parlayWinRate: number;   // 0.0 to 1.0
  totalLegs: number;
  legsHit: number;
  legHitRate: number;      // 0.0 to 1.0
  totalProfit: number;     // Cumulative at $100/parlay
  roi: number;             // Return on investment
}

interface StatPerformance {
  statType: string;
  total: number;
  wins: number;
  winRate: number;
}
```

---

## Endpoints

### GET /parlays/today

Get today's recommended parlays.

**Response**:
```json
{
  "date": "2025-12-16",
  "parlays": [Parlay, ...],
  "totalGames": 12,
  "gamesWithParlays": 8
}
```

### GET /parlays/:date

Get parlays for a specific date.

**Parameters**:
- `date`: YYYY-MM-DD format

**Response**: Same as `/parlays/today`

### GET /parlays/:id

Get single parlay with full details.

**Response**:
```json
{
  "parlay": Parlay
}
```

### GET /settlements/today

Get today's (yesterday's games) settlement results.

**Response**:
```json
{
  "date": "2025-12-15",
  "settlements": [Settlement, ...],
  "summary": {
    "wins": 4,
    "losses": 2,
    "voids": 1,
    "profit": 850.00
  }
}
```

### GET /settlements/:date

Get settlements for a specific date.

### GET /performance

Get overall performance metrics.

**Query Parameters**:
- `season`: Filter by season (e.g., 2026)
- `seasonType`: Filter by type ('regular', 'cup', etc.)
- `days`: Last N days (e.g., 30)

**Response**:
```json
{
  "overall": Performance,
  "byStatType": [StatPerformance, ...],
  "byDirection": {
    "over": { "wins": 50, "total": 70, "winRate": 0.714 },
    "under": { "wins": 8, "total": 8, "winRate": 1.0 }
  },
  "recentTrend": [
    { "date": "2025-12-15", "wins": 4, "total": 6 },
    ...
  ]
}
```

### GET /players/:name/history

Get prop history for a specific player.

**Response**:
```json
{
  "playerName": "LeBron James",
  "totalProps": 15,
  "winRate": 0.733,
  "byStatType": {
    "points": { "total": 8, "wins": 6 },
    "assists": { "total": 7, "wins": 5 }
  },
  "recentProps": [Leg, ...]
}
```

### POST /props/analyze

Analyze a custom prop (for manual research).

**Request**:
```json
{
  "playerName": "LeBron James",
  "statType": "points",
  "line": 25.5,
  "overOdds": -115,
  "underOdds": -105,
  "gameId": "abc123",      // Optional
  "opponentTeam": "DET"    // Optional
}
```

**Response**:
```json
{
  "edgeScore": 0.234,
  "direction": "over",
  "confidence": 0.836,
  "recommendation": "LEAN_OVER",
  "signals": SignalBreakdown,
  "context": {
    "seasonAvg": 23.8,
    "recentAvg": 27.2,
    "vsOpponent": 26.5,
    "isHome": true,
    "isB2B": false
  }
}
```

---

## Error Responses

All endpoints return standard error format:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Parlay not found",
    "details": {}
  }
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `NOT_FOUND` | 404 | Resource not found |
| `INVALID_DATE` | 400 | Invalid date format |
| `PLAYER_NOT_FOUND` | 404 | Player not in database |
| `RATE_LIMITED` | 429 | Too many requests |
| `UNAUTHORIZED` | 401 | Missing/invalid auth |
| `INTERNAL_ERROR` | 500 | Server error |

---

## WebSocket (Future)

For real-time updates during games:

```
WS /ws/parlays

// Subscribe to parlay updates
{ "type": "subscribe", "parlayIds": ["abc123"] }

// Receive leg updates
{ "type": "leg_update", "legId": "xyz", "actualValue": 24, "result": "LOSS" }

// Receive parlay settlement
{ "type": "parlay_settled", "parlayId": "abc123", "result": "LOSS" }
```

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| GET endpoints | 60/min |
| POST /props/analyze | 10/min |
| WebSocket | 1 connection |

---

## Frontend Integration Notes

### Recommended Polling Intervals

| Data | Interval | Note |
|------|----------|------|
| Today's parlays | 5 min | Or on user action |
| Settlements | 15 min | After games end |
| Performance | 1 hour | Relatively static |
| Live game updates | 30 sec | During games (future) |

### Caching Strategy

- Parlays: Cache until game time
- Settlements: Cache for 24 hours
- Performance: Cache for 1 hour
- Player history: Cache for 4 hours

### Status Indicators

```typescript
// Parlay status logic
function getParlayStatus(parlay: Parlay): string {
  if (parlay.settlement) {
    return parlay.settlement.result;
  }
  const gameTime = new Date(parlay.gameDate + 'T19:00:00-05:00');
  if (new Date() > gameTime) {
    return 'IN_PROGRESS';
  }
  return 'PENDING';
}
```

---

## Implementation Priority

1. **MVP** (Week 1):
   - GET /parlays/today
   - GET /settlements/today
   - GET /performance

2. **Phase 2** (Week 2):
   - GET /parlays/:date
   - GET /parlays/:id
   - GET /settlements/:date

3. **Phase 3** (Week 3-4):
   - POST /props/analyze
   - GET /players/:name/history
   - WebSocket support
