"""
NBA SGP Database Manager

Handles Supabase operations for NBA SGP parlays, legs, and settlements.
Schema aligned with NHL pattern (most comprehensive).

Tables:
    - nba_sgp_parlays: Parent parlay records
    - nba_sgp_legs: Individual prop legs within parlays
    - nba_sgp_settlements: Settlement records for parlays

Following NHL pattern (not NFL) because:
    - No 'week' column (NBA doesn't have weeks like NFL/NCAAF)
    - Has 'season_type' for regular/playoffs/cup/playin
    - Rich leg schema with player_id, probabilities, pipeline context
"""

import os
import uuid
import logging
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Lazy import supabase to allow module to load without it
_supabase_client = None


def _get_supabase_client():
    """Lazy-load Supabase client."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    try:
        from supabase import create_client, Client
    except ImportError:
        raise ImportError(
            "supabase package not installed. Run: pip install supabase"
        )

    # Load environment variables
    for env_path in ['.env.local', '.env', '../.env.local', '../.env']:
        if os.path.exists(env_path):
            load_dotenv(dotenv_path=env_path)
            break

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY required in environment")

    _supabase_client = create_client(url, key)
    return _supabase_client


class NBASGPDBManager:
    """
    Manages NBA SGP tables (aligned with NHL architecture):
    - nba_sgp_parlays: Parent parlay records with thesis, combined odds
    - nba_sgp_legs: Individual prop legs within parlays
    - nba_sgp_settlements: Settlement records with profit tracking

    Uses Supabase Python client for simplicity.
    """

    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        """
        Initialize database manager.

        Args:
            url: Optional Supabase URL (defaults to SUPABASE_URL env var)
            key: Optional Supabase key (defaults to SUPABASE_KEY env var)
        """
        if url and key:
            from supabase import create_client
            self.client = create_client(url, key)
        else:
            self.client = _get_supabase_client()

        logger.info("[NBA SGP DB] Connected to Supabase")

    # =========================================================================
    # Parlay Operations
    # =========================================================================

    def save_parlay(self, parlay: Dict) -> Dict:
        """
        Save a parlay and its legs to the database.

        Uses upsert based on unique constraint:
        (season, season_type, parlay_type, game_id)

        Args:
            parlay: Parlay dict with keys:
                - id: UUID (optional, generated if missing)
                - parlay_type: 'primary', 'value_play', 'theme_stack', etc.
                - game_id: Odds API event ID
                - game_date: Date in YYYY-MM-DD format
                - home_team, away_team: Team abbreviations
                - game_slot: 'AFTERNOON', 'EVENING', 'LATE'
                - total_legs: Number of legs
                - combined_odds: American odds (e.g., +450)
                - implied_probability: 0.0 to 1.0
                - thesis: Narrative explanation
                - season: Year (e.g., 2026 for 2025-26)
                - season_type: 'regular', 'playoffs', 'cup', 'playin'
                - legs: List of leg dicts

        Returns:
            Saved parlay record with id
        """
        parlay_id = parlay.get("id") or str(uuid.uuid4())
        legs = parlay.pop("legs", [])

        # Check if parlay exists by unique constraint
        existing = self.client.table("nba_sgp_parlays").select("id").eq(
            "season", parlay["season"]
        ).eq(
            "season_type", parlay.get("season_type", "regular")
        ).eq(
            "parlay_type", parlay["parlay_type"]
        ).eq(
            "game_id", parlay["game_id"]
        ).execute()

        # If exists, use existing ID and delete old legs
        if existing.data:
            parlay_id = existing.data[0]["id"]
            self.client.table("nba_sgp_legs").delete().eq(
                "parlay_id", parlay_id
            ).execute()
            logger.debug(f"[NBA SGP DB] Updating existing parlay {parlay_id[:8]}...")

        # Prepare parlay record
        parlay_record = {
            "id": parlay_id,
            "parlay_type": parlay["parlay_type"],
            "game_id": parlay["game_id"],
            "game_date": str(parlay["game_date"]),
            "home_team": parlay["home_team"],
            "away_team": parlay["away_team"],
            "game_slot": parlay.get("game_slot"),
            "total_legs": parlay["total_legs"],
            "combined_odds": parlay.get("combined_odds"),
            "implied_probability": parlay.get("implied_probability"),
            "thesis": parlay.get("thesis"),
            "season": parlay["season"],
            "season_type": parlay.get("season_type", "regular"),
        }

        # Upsert parlay
        result = self.client.table("nba_sgp_parlays").upsert(
            parlay_record,
            on_conflict="season,season_type,parlay_type,game_id"
        ).execute()

        # Insert legs
        for i, leg in enumerate(legs):
            leg_record = {
                "id": leg.get("id") or str(uuid.uuid4()),
                "parlay_id": parlay_id,
                "leg_number": leg.get("leg_number", i + 1),
                "player_name": leg["player_name"],
                "player_id": leg.get("player_id"),
                "team": leg.get("team"),
                "position": leg.get("position"),
                "stat_type": leg["stat_type"],
                "line": leg.get("line"),
                "direction": leg.get("direction"),
                "odds": leg.get("odds"),
                "edge_pct": leg.get("edge_pct"),
                "confidence": leg.get("confidence"),
                "model_probability": leg.get("model_probability"),
                "market_probability": leg.get("market_probability"),
                "primary_reason": leg.get("primary_reason"),
                "supporting_reasons": leg.get("supporting_reasons", []),
                "risk_factors": leg.get("risk_factors", []),
                "signals": leg.get("signals", {}),
                "pipeline_score": leg.get("pipeline_score"),
                "pipeline_confidence": leg.get("pipeline_confidence"),
                "pipeline_rank": leg.get("pipeline_rank"),
            }
            self.client.table("nba_sgp_legs").insert(leg_record).execute()

        logger.info(
            f"[NBA SGP DB] Saved {parlay['parlay_type']} parlay "
            f"({len(legs)} legs) for {parlay['home_team']} vs {parlay['away_team']}"
        )

        return result.data[0] if result.data else parlay_record

    def get_parlays_by_date(self, game_date: date) -> List[Dict]:
        """
        Get all parlays for a specific date with their legs.

        Args:
            game_date: Game date

        Returns:
            List of parlay dicts with nested legs
        """
        result = self.client.table("nba_sgp_parlays").select(
            "*, nba_sgp_legs(*)"
        ).eq(
            "game_date", str(game_date)
        ).order("created_at", desc=True).execute()

        return result.data

    def get_unsettled_parlays(
        self,
        game_date: Optional[date] = None,
        season: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get parlays that haven't been settled yet.

        Args:
            game_date: Optional filter by game date
            season: Optional filter by season

        Returns:
            List of parlay dicts with nested legs
        """
        # Get parlays that don't have a settlement record
        # Using left join approach: get all parlays, then filter
        query = self.client.table("nba_sgp_parlays").select(
            "*, nba_sgp_legs(*)"
        )

        if game_date:
            query = query.eq("game_date", str(game_date))
        if season:
            query = query.eq("season", season)

        parlays = query.execute().data

        if not parlays:
            return []

        # Get parlay IDs that have settlements
        parlay_ids = [p["id"] for p in parlays]
        settled = self.client.table("nba_sgp_settlements").select(
            "parlay_id"
        ).in_("parlay_id", parlay_ids).execute()

        settled_ids = {s["parlay_id"] for s in settled.data}

        # Return only unsettled
        return [p for p in parlays if p["id"] not in settled_ids]

    # =========================================================================
    # Leg Operations
    # =========================================================================

    def update_leg_result(
        self,
        leg_id: str,
        actual_value: float,
        result: str,  # 'WIN', 'LOSS', 'PUSH', 'VOID'
    ) -> None:
        """
        Update a leg with settlement result.

        Args:
            leg_id: UUID of leg
            actual_value: Actual stat value from box score
            result: 'WIN', 'LOSS', 'PUSH', or 'VOID'
        """
        self.client.table("nba_sgp_legs").update({
            "actual_value": actual_value,
            "result": result,
        }).eq("id", leg_id).execute()

        logger.debug(f"[NBA SGP DB] Updated leg {leg_id[:8]}: {result}")

    def get_legs_by_player(
        self,
        player_name: str,
        stat_type: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get all legs for a specific player.

        Useful for tracking player-level performance.

        Args:
            player_name: Player name
            stat_type: Optional filter by stat type

        Returns:
            List of leg records
        """
        query = self.client.table("nba_sgp_legs").select("*").eq(
            "player_name", player_name
        )

        if stat_type:
            query = query.eq("stat_type", stat_type)

        return query.execute().data

    # =========================================================================
    # Settlement Operations
    # =========================================================================

    def settle_parlay(
        self,
        parlay_id: str,
        legs_hit: int,
        total_legs: int,
        result: str,  # 'WIN', 'LOSS', 'VOID'
        profit: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> Dict:
        """
        Create settlement record for a parlay.

        Args:
            parlay_id: UUID of parlay
            legs_hit: Number of legs that hit
            total_legs: Total number of legs
            result: 'WIN', 'LOSS', or 'VOID'
            profit: Profit at $100 stake (optional)
            notes: Settlement notes (optional)

        Returns:
            Settlement record
        """
        settlement = {
            "id": str(uuid.uuid4()),
            "parlay_id": parlay_id,
            "legs_hit": legs_hit,
            "total_legs": total_legs,
            "result": result,
            "profit": profit,
            "notes": notes,
        }

        # Upsert in case we need to re-settle
        result_data = self.client.table("nba_sgp_settlements").upsert(
            settlement,
            on_conflict="parlay_id"
        ).execute()

        logger.info(
            f"[NBA SGP DB] Settled parlay {parlay_id[:8]}: "
            f"{result} ({legs_hit}/{total_legs} legs)"
        )

        return result_data.data[0] if result_data.data else settlement

    def get_settlements_by_date(self, game_date: date) -> List[Dict]:
        """
        Get all settlements for parlays on a specific date.

        Args:
            game_date: Game date

        Returns:
            List of settlement records with parlay details
        """
        # Get parlay IDs for the date
        parlays = self.client.table("nba_sgp_parlays").select("id").eq(
            "game_date", str(game_date)
        ).execute()

        if not parlays.data:
            return []

        parlay_ids = [p["id"] for p in parlays.data]

        # Get settlements
        settlements = self.client.table("nba_sgp_settlements").select(
            "*, nba_sgp_parlays(*)"
        ).in_("parlay_id", parlay_ids).execute()

        return settlements.data

    # =========================================================================
    # Performance Analytics
    # =========================================================================

    def get_performance_summary(
        self,
        season: Optional[int] = None,
        season_type: Optional[str] = None,
    ) -> Dict:
        """
        Get performance summary.

        Args:
            season: Optional filter by season
            season_type: Optional filter by season type

        Returns:
            Dict with performance metrics
        """
        # Get all settlements with parlay info
        query = self.client.table("nba_sgp_settlements").select(
            "*, nba_sgp_parlays!inner(*)"
        )

        if season:
            query = query.eq("nba_sgp_parlays.season", season)
        if season_type:
            query = query.eq("nba_sgp_parlays.season_type", season_type)

        settlements = query.execute().data

        if not settlements:
            return {
                "total_parlays": 0,
                "wins": 0,
                "losses": 0,
                "voids": 0,
                "parlay_win_rate": 0.0,
                "total_legs": 0,
                "legs_hit": 0,
                "leg_hit_rate": 0.0,
            }

        total = len(settlements)
        wins = sum(1 for s in settlements if s["result"] == "WIN")
        losses = sum(1 for s in settlements if s["result"] == "LOSS")
        voids = sum(1 for s in settlements if s["result"] == "VOID")

        total_legs = sum(s["total_legs"] for s in settlements)
        legs_hit = sum(s["legs_hit"] for s in settlements)

        return {
            "total_parlays": total,
            "wins": wins,
            "losses": losses,
            "voids": voids,
            "parlay_win_rate": wins / (wins + losses) if (wins + losses) > 0 else 0.0,
            "total_legs": total_legs,
            "legs_hit": legs_hit,
            "leg_hit_rate": legs_hit / total_legs if total_legs > 0 else 0.0,
        }

    def get_player_performance(
        self,
        min_legs: int = 3,
        season: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get performance by player.

        Args:
            min_legs: Minimum legs to include player
            season: Optional filter by season

        Returns:
            List of player performance records
        """
        # Get all settled legs
        query = self.client.table("nba_sgp_legs").select(
            "player_name, team, stat_type, result, edge_pct"
        ).not_.is_("result", "null")

        legs = query.execute().data

        if not legs:
            return []

        # Aggregate by player + stat type
        player_stats = {}
        for leg in legs:
            key = (leg["player_name"], leg["stat_type"])
            if key not in player_stats:
                player_stats[key] = {
                    "player_name": leg["player_name"],
                    "team": leg["team"],
                    "stat_type": leg["stat_type"],
                    "total": 0,
                    "wins": 0,
                    "edge_sum": 0.0,
                }

            player_stats[key]["total"] += 1
            if leg["result"] == "WIN":
                player_stats[key]["wins"] += 1
            if leg.get("edge_pct"):
                player_stats[key]["edge_sum"] += float(leg["edge_pct"])

        # Filter and format
        results = []
        for stats in player_stats.values():
            if stats["total"] >= min_legs:
                results.append({
                    "player_name": stats["player_name"],
                    "team": stats["team"],
                    "stat_type": stats["stat_type"],
                    "times_recommended": stats["total"],
                    "wins": stats["wins"],
                    "win_rate": stats["wins"] / stats["total"],
                    "avg_edge": stats["edge_sum"] / stats["total"],
                })

        # Sort by times recommended, then win rate
        results.sort(key=lambda x: (-x["times_recommended"], -x["win_rate"]))

        return results

    def get_signal_performance(
        self,
        season: Optional[int] = None,
        min_strength: float = 0.05
    ) -> List[Dict]:
        """
        Get performance by signal type.

        Analyzes which signals are most predictive by only counting
        signals that had meaningful strength (|strength| >= min_strength).

        Args:
            season: Optional filter by season
            min_strength: Minimum |strength| to count signal as active (default 0.05)

        Returns:
            List of signal performance records with direction breakdown
        """
        # Get all settled legs with signals and direction
        query = self.client.table("nba_sgp_legs").select(
            "signals, result, direction"
        ).not_.is_("result", "null").not_.is_("signals", "null")

        legs = query.execute().data

        if not legs:
            return []

        # Aggregate by signal type - only count signals with meaningful strength
        signal_stats = {}
        for leg in legs:
            if not leg.get("signals") or leg["result"] in ("VOID", "PUSH"):
                continue

            leg_direction = leg.get("direction", "over")
            leg_won = leg["result"] == "WIN"

            for signal_name, strength in leg["signals"].items():
                # Only count if signal had meaningful strength
                if strength is None or abs(strength) < min_strength:
                    continue

                if signal_name not in signal_stats:
                    signal_stats[signal_name] = {
                        "total": 0,
                        "wins": 0,
                        "over_total": 0,
                        "over_wins": 0,
                        "under_total": 0,
                        "under_wins": 0,
                        "aligned_total": 0,  # Signal direction matched bet direction
                        "aligned_wins": 0,
                        "strength_sum": 0.0,
                    }

                stats = signal_stats[signal_name]
                stats["total"] += 1
                stats["strength_sum"] += abs(strength)

                if leg_won:
                    stats["wins"] += 1

                # Track by direction
                if leg_direction == "over":
                    stats["over_total"] += 1
                    if leg_won:
                        stats["over_wins"] += 1
                else:
                    stats["under_total"] += 1
                    if leg_won:
                        stats["under_wins"] += 1

                # Track alignment (signal direction matched bet direction)
                signal_suggests_over = strength > 0
                bet_was_over = leg_direction == "over"
                if signal_suggests_over == bet_was_over:
                    stats["aligned_total"] += 1
                    if leg_won:
                        stats["aligned_wins"] += 1

        # Format results
        results = []
        for signal_name, stats in signal_stats.items():
            if stats["total"] > 0:
                result = {
                    "signal_type": signal_name,
                    "total_legs": stats["total"],
                    "wins": stats["wins"],
                    "win_rate": stats["wins"] / stats["total"],
                    "avg_strength": stats["strength_sum"] / stats["total"],
                }

                # Add direction breakdown if meaningful sample
                if stats["over_total"] >= 5:
                    result["over_win_rate"] = stats["over_wins"] / stats["over_total"]
                if stats["under_total"] >= 5:
                    result["under_win_rate"] = stats["under_wins"] / stats["under_total"]

                # Add alignment rate (when signal agreed with bet direction)
                if stats["aligned_total"] >= 5:
                    result["aligned_win_rate"] = stats["aligned_wins"] / stats["aligned_total"]
                    result["aligned_legs"] = stats["aligned_total"]

                results.append(result)

        # Sort by win rate
        results.sort(key=lambda x: -x["win_rate"])

        return results

    def get_signal_performance_by_stat(
        self,
        min_strength: float = 0.05
    ) -> Dict[str, List[Dict]]:
        """
        Get signal performance broken down by stat type.

        Critical for understanding why certain stat types underperform.
        For example: which signals work for points but fail for rebounds?

        Args:
            min_strength: Minimum |strength| to count signal as active

        Returns:
            Dict mapping stat_type -> list of signal performance records
        """
        # Get all settled legs with signals, direction, and stat_type
        query = self.client.table("nba_sgp_legs").select(
            "signals, result, direction, stat_type"
        ).not_.is_("result", "null").not_.is_("signals", "null")

        legs = query.execute().data

        if not legs:
            return {}

        # Aggregate by stat_type -> signal_type
        stat_signal_stats = {}

        for leg in legs:
            if not leg.get("signals") or leg["result"] in ("VOID", "PUSH"):
                continue

            stat_type = leg.get("stat_type", "unknown")
            leg_direction = leg.get("direction", "over")
            leg_won = leg["result"] == "WIN"

            if stat_type not in stat_signal_stats:
                stat_signal_stats[stat_type] = {}

            for signal_name, strength in leg["signals"].items():
                if strength is None or abs(strength) < min_strength:
                    continue

                if signal_name not in stat_signal_stats[stat_type]:
                    stat_signal_stats[stat_type][signal_name] = {
                        "total": 0,
                        "wins": 0,
                        "over_total": 0,
                        "over_wins": 0,
                        "under_total": 0,
                        "under_wins": 0,
                    }

                stats = stat_signal_stats[stat_type][signal_name]
                stats["total"] += 1
                if leg_won:
                    stats["wins"] += 1

                if leg_direction == "over":
                    stats["over_total"] += 1
                    if leg_won:
                        stats["over_wins"] += 1
                else:
                    stats["under_total"] += 1
                    if leg_won:
                        stats["under_wins"] += 1

        # Format results
        results = {}
        for stat_type, signal_data in stat_signal_stats.items():
            results[stat_type] = []
            for signal_name, stats in signal_data.items():
                if stats["total"] >= 3:  # Need minimum sample
                    entry = {
                        "signal_type": signal_name,
                        "total": stats["total"],
                        "wins": stats["wins"],
                        "win_rate": stats["wins"] / stats["total"],
                    }
                    if stats["over_total"] >= 3:
                        entry["over_win_rate"] = stats["over_wins"] / stats["over_total"]
                        entry["over_total"] = stats["over_total"]
                    if stats["under_total"] >= 3:
                        entry["under_win_rate"] = stats["under_wins"] / stats["under_total"]
                        entry["under_total"] = stats["under_total"]
                    results[stat_type].append(entry)

            # Sort by win rate
            results[stat_type].sort(key=lambda x: -x["win_rate"])

        return results

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def test_connection(self) -> bool:
        """Test database connection."""
        try:
            # Simple query to test connection
            self.client.table("nba_sgp_parlays").select("id").limit(1).execute()
            return True
        except Exception as e:
            logger.error(f"[NBA SGP DB] Connection test failed: {e}")
            return False

    def get_latest_parlay_date(self) -> Optional[date]:
        """Get the most recent parlay date."""
        result = self.client.table("nba_sgp_parlays").select(
            "game_date"
        ).order("game_date", desc=True).limit(1).execute()

        if result.data:
            return datetime.strptime(result.data[0]["game_date"], "%Y-%m-%d").date()
        return None

    def clear_settlements_for_date(self, game_date: date) -> int:
        """
        Clear settlement records for parlays on a specific date.
        Also clears leg results.

        Args:
            game_date: Game date to clear

        Returns:
            Number of settlements cleared
        """
        # Get parlay IDs for the date
        parlays = self.client.table("nba_sgp_parlays").select("id").eq(
            "game_date", str(game_date)
        ).execute()

        if not parlays.data:
            return 0

        parlay_ids = [p["id"] for p in parlays.data]

        # Delete settlements
        self.client.table("nba_sgp_settlements").delete().in_(
            "parlay_id", parlay_ids
        ).execute()

        # Clear leg results
        for pid in parlay_ids:
            self.client.table("nba_sgp_legs").update({
                "actual_value": None,
                "result": None
            }).eq("parlay_id", pid).execute()

        logger.info(f"[NBA SGP DB] Cleared {len(parlay_ids)} settlements for {game_date}")
        return len(parlay_ids)


# Singleton instance
_db_manager: Optional[NBASGPDBManager] = None


def get_db_manager() -> NBASGPDBManager:
    """Get singleton database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = NBASGPDBManager()
    return _db_manager
