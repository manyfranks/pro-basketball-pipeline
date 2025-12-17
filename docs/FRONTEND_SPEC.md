# NBA SGP Engine - Frontend Specification

**Version**: 1.0
**Target**: Web + Mobile Responsive
**Framework Suggestion**: Next.js 14 + Tailwind CSS + shadcn/ui

---

## Overview

The NBA SGP Engine frontend provides a dashboard for viewing recommended parlays, tracking performance, and analyzing individual props.

## User Flows

### 1. Daily View (Primary)
```
User opens app
  → See today's date prominently
  → See today's recommended parlays (cards)
  → Each card shows: teams, legs, odds, confidence
  → Can expand card for signal breakdown
  → After games: see settlement status
```

### 2. Performance Dashboard
```
User clicks "Performance"
  → See overall win rate (big number)
  → See profit/loss chart over time
  → See breakdown by stat type
  → See recent results list
```

### 3. Historical View
```
User clicks calendar
  → Select date
  → See parlays for that date
  → See settlement results
```

---

## Page Specifications

### Home Page (`/`)

**Layout**:
```
┌─────────────────────────────────────────────────┐
│  [Logo]  Today's Picks   Performance   History  │
├─────────────────────────────────────────────────┤
│                                                 │
│  📅 December 16, 2025        [Refresh ↻]       │
│                                                 │
│  ┌─────────────────────────────────────────┐   │
│  │  LAL @ BOS  •  7:30 PM ET              │   │
│  │                                         │   │
│  │  [Anthony Davis]  Rebounds O 11.5 -115 │   │
│  │  [Jayson Tatum]   Points O 28.5 -110   │   │
│  │  [LeBron James]   Assists O 7.5 +100   │   │
│  │                                         │   │
│  │  Combined: +425  │  Confidence: 78%    │   │
│  │                                         │   │
│  │  [View Details ▼]                       │   │
│  └─────────────────────────────────────────┘   │
│                                                 │
│  ┌─────────────────────────────────────────┐   │
│  │  DET @ NYK  •  7:00 PM ET              │   │
│  │  ...                                    │   │
│  └─────────────────────────────────────────┘   │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Components**:
- `ParlayCard`: Main card component
- `LegRow`: Individual leg within card
- `OddsBadge`: Displays odds with color coding
- `ConfidenceBar`: Visual confidence indicator

### Parlay Card (Expanded)

```
┌─────────────────────────────────────────────────┐
│  LAL @ BOS  •  7:30 PM ET                      │
├─────────────────────────────────────────────────┤
│                                                 │
│  LEG 1: Anthony Davis - Rebounds Over 11.5     │
│  ├── Odds: -115                                │
│  ├── Edge: +42%  Confidence: 85%              │
│  ├── Season Avg: 12.3  |  Recent: 13.8        │
│  └── Signal: [========] Correlation +0.3       │
│             [======  ] Matchup +0.2            │
│             [====    ] Trend +0.15             │
│                                                 │
│  LEG 2: Jayson Tatum - Points Over 28.5       │
│  ├── Odds: -110                                │
│  ├── Edge: +38%  Confidence: 82%              │
│  ...                                           │
│                                                 │
├─────────────────────────────────────────────────┤
│  THESIS:                                        │
│  "High-scoring game expected (O/U 232). Davis  │
│  averaging 13.8 rebounds in last 5 games vs    │
│  BOS's weak interior defense..."               │
├─────────────────────────────────────────────────┤
│  Combined: +425  |  Implied: 18.2%             │
│  [Copy to Clipboard]  [Share]                   │
└─────────────────────────────────────────────────┘
```

### Performance Page (`/performance`)

```
┌─────────────────────────────────────────────────┐
│  [Logo]  Today's Picks   Performance   History  │
├─────────────────────────────────────────────────┤
│                                                 │
│  OVERALL PERFORMANCE                            │
│                                                 │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐         │
│  │  59.3%  │  │  +$850  │  │  35     │         │
│  │Win Rate │  │ Profit  │  │ Parlays │         │
│  └─────────┘  └─────────┘  └─────────┘         │
│                                                 │
│  PROFIT OVER TIME                               │
│  [═══════════════════════════════════]         │
│  ▲ $1000                                       │
│  │    ╱╲    ╱╲╱╲                              │
│  │   ╱  ╲  ╱    ╲                             │
│  │──╱────╲╱──────╲──────────────────          │
│  └─────────────────────────────────────        │
│    Nov 14    Nov 21    Dec 9    Dec 13         │
│                                                 │
│  BY STAT TYPE                                   │
│  Points:    ████████████████  81% (17/21)     │
│  Assists:   ██████████████    75% (27/36)     │
│  Rebounds:  █████████████     72% (13/18)     │
│                                                 │
│  RECENT RESULTS                                 │
│  Dec 13: 1W / 3L / 6V  •  -$200               │
│  Dec 10: 1W / 1L / 1V  •  +$50                │
│  Dec 09: 1W / 1L / 1V  •  +$50                │
│  ...                                           │
└─────────────────────────────────────────────────┘
```

### Settlement View (After Games)

```
┌─────────────────────────────────────────────────┐
│  LAL @ BOS  •  FINAL: LAL 118 - BOS 112       │
├─────────────────────────────────────────────────┤
│  ✅ WIN  │  +$525                               │
│                                                 │
│  ✅ Anthony Davis - Rebounds O 11.5            │
│     Actual: 14  │  Result: WIN                 │
│                                                 │
│  ✅ Jayson Tatum - Points O 28.5              │
│     Actual: 31  │  Result: WIN                 │
│                                                 │
│  ✅ LeBron James - Assists O 7.5              │
│     Actual: 9   │  Result: WIN                 │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## Component Library

### ParlayCard

```tsx
interface ParlayCardProps {
  parlay: Parlay;
  expanded?: boolean;
  onToggle?: () => void;
  showSettlement?: boolean;
}

// States: pending, in_progress, win, loss, void
```

### LegRow

```tsx
interface LegRowProps {
  leg: Leg;
  showSignals?: boolean;
  showResult?: boolean;
}
```

### OddsBadge

```tsx
interface OddsBadgeProps {
  odds: number;
  size?: 'sm' | 'md' | 'lg';
}

// Color: positive odds (green), negative odds (default)
```

### ConfidenceBar

```tsx
interface ConfidenceBarProps {
  value: number;  // 0-100
  size?: 'sm' | 'md' | 'lg';
}

// Color gradient: red (0-40) → yellow (40-70) → green (70-100)
```

### SignalBreakdown

```tsx
interface SignalBreakdownProps {
  signals: SignalBreakdown;
  compact?: boolean;
}

// Shows bar chart of signal contributions
```

### ResultBadge

```tsx
interface ResultBadgeProps {
  result: 'WIN' | 'LOSS' | 'PUSH' | 'VOID' | 'PENDING';
}

// Colors: WIN (green), LOSS (red), PUSH (gray), VOID (gray), PENDING (blue)
```

---

## Color Palette

```css
/* Primary */
--primary: #2563eb;        /* Blue - primary actions */
--primary-dark: #1d4ed8;

/* Results */
--win: #16a34a;            /* Green */
--loss: #dc2626;           /* Red */
--void: #6b7280;           /* Gray */
--pending: #2563eb;        /* Blue */

/* Backgrounds */
--bg-primary: #ffffff;
--bg-secondary: #f9fafb;
--bg-card: #ffffff;
--bg-dark: #111827;

/* Text */
--text-primary: #111827;
--text-secondary: #6b7280;
--text-muted: #9ca3af;

/* Accents */
--accent-high: #16a34a;    /* High confidence */
--accent-medium: #eab308;  /* Medium confidence */
--accent-low: #dc2626;     /* Low confidence */
```

---

## Mobile Considerations

### Responsive Breakpoints

```css
/* Mobile: < 640px */
/* Tablet: 640px - 1024px */
/* Desktop: > 1024px */
```

### Mobile Layout

```
┌─────────────────────┐
│  NBA SGP  [≡]       │
├─────────────────────┤
│ 📅 Dec 16, 2025     │
├─────────────────────┤
│ ┌─────────────────┐ │
│ │ LAL @ BOS 7:30p │ │
│ │ 3 legs • +425   │ │
│ │ [View ▼]        │ │
│ └─────────────────┘ │
│ ┌─────────────────┐ │
│ │ DET @ NYK 7:00p │ │
│ │ 3 legs • +380   │ │
│ │ [View ▼]        │ │
│ └─────────────────┘ │
├─────────────────────┤
│ [Today] [Stats] [⚙] │
└─────────────────────┘
```

---

## State Management

### Global State

```typescript
interface AppState {
  // Data
  todayParlays: Parlay[];
  settlements: Settlement[];
  performance: Performance;

  // UI
  selectedDate: Date;
  expandedParlayId: string | null;
  isLoading: boolean;

  // User preferences
  theme: 'light' | 'dark';
  notifications: boolean;
}
```

### Caching Strategy

```typescript
// Use SWR or React Query with these settings
const cacheConfig = {
  parlays: {
    staleTime: 5 * 60 * 1000,      // 5 minutes
    cacheTime: 30 * 60 * 1000,     // 30 minutes
  },
  settlements: {
    staleTime: 15 * 60 * 1000,     // 15 minutes
    cacheTime: 24 * 60 * 60 * 1000, // 24 hours
  },
  performance: {
    staleTime: 60 * 60 * 1000,     // 1 hour
    cacheTime: 4 * 60 * 60 * 1000, // 4 hours
  },
};
```

---

## Notifications

### Push Notification Types

1. **New Parlays Available**
   - Trigger: Daily at 6 PM ET
   - Content: "Today's NBA picks are ready! 8 parlays available."

2. **Parlay Settlement**
   - Trigger: After game ends
   - Content: "LAL @ BOS parlay: WIN! +$525"

3. **Performance Milestone**
   - Trigger: On achievement
   - Content: "You're on a 5-game win streak!"

---

## Future Features

### Phase 2
- [ ] Dark mode
- [ ] Custom prop analyzer
- [ ] Bankroll tracking
- [ ] Notification preferences

### Phase 3
- [ ] Live game tracking
- [ ] Social sharing
- [ ] Leaderboard
- [ ] Historical analysis tools

### Phase 4
- [ ] Native mobile apps
- [ ] Sportsbook integrations
- [ ] AI chat assistant
