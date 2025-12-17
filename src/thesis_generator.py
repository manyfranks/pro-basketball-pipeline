"""
NBA SGP Parlay Thesis Generator

Generates natural language thesis narratives for SGP parlays using LLM.
Falls back to rule-based generation if LLM unavailable.

Usage:
    from src.thesis_generator import ThesisGenerator, generate_parlay_thesis

    generator = ThesisGenerator()
    thesis = generator.generate_thesis(game_data, legs)
"""

import os
import json
import logging
import requests
from typing import Dict, List, Optional
from collections import defaultdict
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
for path in ['.env.local', '.env', '../.env.local', '../.env']:
    if os.path.exists(path):
        load_dotenv(dotenv_path=path)
        break


class ThesisGenerator:
    """
    Generates thesis narratives for NBA SGP parlays.

    Uses OpenRouter LLM for natural narratives with rule-based fallback.
    """

    SYSTEM_PROMPT = """You are an expert NBA betting analyst writing thesis statements for Same Game Parlays (SGPs).

Your thesis should:
- Be 2-3 sentences maximum
- Explain WHY these legs correlate well together
- Reference specific player roles, matchups, pace, or game context
- Sound confident but analytical
- NOT use bullet points or lists

Examples of good theses:
- "Phoenix's up-tempo offense against Portland's porous perimeter defense creates an ideal environment for Booker's scoring. Stacking Durant's rebounds with the expected game total of 230+ provides positive correlation for a high-scoring affair."
- "Milwaukee's interior dominance should generate volume for Antetokounmpo against Cleveland's switching defense. His playmaking uptick with Lillard creates assist correlation in half-court sets."
- "Boston's league-best offense faces a Nets team allowing 118 PPG. Tatum and Brown's complementary scoring styles make this an optimal offensive stack with implied totals over 225."

Return ONLY the thesis text, no JSON, no quotes, no extra formatting."""

    def __init__(self, use_llm: bool = True):
        """
        Initialize thesis generator.

        Args:
            use_llm: Whether to attempt LLM generation (default: True)
        """
        self.use_llm = use_llm
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        self.model = os.getenv('OPENROUTER_MODEL_NAME', 'google/gemini-2.0-flash-001')

        if not self.api_key and use_llm:
            logger.warning("[ThesisGenerator] No OPENROUTER_API_KEY found, will use rule-based fallback")

    def generate_thesis(self, game_data: Dict, legs: List[Dict]) -> str:
        """
        Generate thesis for a parlay.

        Args:
            game_data: Game context (home_team, away_team, game_total, etc.)
            legs: List of leg dictionaries with player info, stats, edges

        Returns:
            Thesis string
        """
        if self.use_llm and self.api_key:
            try:
                llm_thesis = self._generate_llm_thesis(game_data, legs)
                if llm_thesis and len(llm_thesis) > 20:
                    return llm_thesis
            except Exception as e:
                logger.warning(f"[ThesisGenerator] LLM failed, using fallback: {e}")

        return self._generate_rule_based_thesis(game_data, legs)

    def _generate_llm_thesis(self, game_data: Dict, legs: List[Dict]) -> Optional[str]:
        """Generate thesis using LLM via OpenRouter."""
        prompt = self._build_prompt(game_data, legs)

        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/orio/nba-sgp-engine",
                    "X-Title": "NBA SGP Thesis Generator"
                },
                json={
                    "model": self.model,
                    "max_tokens": 200,
                    "temperature": 0.7,
                    "messages": [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ]
                },
                timeout=30
            )

            response.raise_for_status()
            result = response.json()
            thesis = result['choices'][0]['message']['content'].strip()

            # Clean up any quotes or extra formatting
            thesis = thesis.strip('"\'')

            logger.info(f"[ThesisGenerator] Generated LLM thesis: {thesis[:50]}...")
            return thesis

        except requests.exceptions.Timeout:
            logger.warning("[ThesisGenerator] LLM request timed out")
            return None
        except Exception as e:
            logger.warning(f"[ThesisGenerator] LLM error: {e}")
            return None

    def _build_prompt(self, game_data: Dict, legs: List[Dict]) -> str:
        """Build prompt for LLM thesis generation."""
        home = game_data.get('home_team', 'HOME')
        away = game_data.get('away_team', 'AWAY')
        game_total = game_data.get('game_total', 220)
        spread = game_data.get('spread', 0)

        # Format legs
        legs_text = []
        for i, leg in enumerate(legs, 1):
            player = leg.get('player_name', 'Unknown')
            team = leg.get('team', '?')
            stat = leg.get('stat_type', 'points')
            line = leg.get('line', 0.5)
            direction = leg.get('direction', 'over')
            edge = leg.get('edge_pct', 0)
            position = leg.get('position', '?')
            reason = leg.get('primary_reason', '')

            legs_text.append(
                f"{i}. {player} ({team}, {position}) - {stat} {direction.upper()} {line} | "
                f"Edge: {edge:.1f}% | {reason}"
            )

        # Analyze composition
        stat_types = [leg.get('stat_type', '') for leg in legs]
        teams = [leg.get('team', '') for leg in legs]

        team_counts = defaultdict(int)
        for t in teams:
            team_counts[t] += 1

        stacked_team = max(team_counts.keys(), key=lambda x: team_counts[x]) if team_counts else None
        is_stacked = team_counts.get(stacked_team, 0) >= 2

        composition_notes = []
        if stat_types.count('points') >= 2:
            composition_notes.append("scoring-focused stack")
        if stat_types.count('rebounds') >= 2:
            composition_notes.append("rebounding play")
        if stat_types.count('assists') >= 2:
            composition_notes.append("playmaking correlation")
        if 'points_rebounds_assists' in stat_types:
            composition_notes.append("all-around production")
        if is_stacked:
            composition_notes.append(f"{stacked_team} team stack")

        avg_edge = sum(leg.get('edge_pct', 0) for leg in legs) / len(legs) if legs else 0

        prompt = f"""Write a thesis for this NBA Same Game Parlay:

MATCHUP: {away} @ {home}
GAME TOTAL: {game_total}
SPREAD: {home} {spread:+.1f}

LEGS:
{chr(10).join(legs_text)}

PARLAY CHARACTERISTICS:
- Total legs: {len(legs)}
- Average edge: {avg_edge:.1f}%
- Composition: {', '.join(composition_notes) if composition_notes else 'mixed'}

Write a 2-3 sentence thesis explaining why these legs correlate well together."""

        return prompt

    def _generate_rule_based_thesis(self, game_data: Dict, legs: List[Dict]) -> str:
        """Generate thesis using rule-based logic (fallback)."""
        home = game_data.get('home_team', 'HOME')
        away = game_data.get('away_team', 'AWAY')
        game_total = game_data.get('game_total', 220)

        stat_types = [leg.get('stat_type', '') for leg in legs]
        teams = [leg.get('team', 'UNK') for leg in legs]
        avg_edge = sum(leg.get('edge_pct', 0) for leg in legs) / len(legs) if legs else 0

        thesis_parts = []

        # Game script context
        if game_total and game_total > 225:
            thesis_parts.append(f"High-scoring game expected ({game_total} total)")
        elif game_total and game_total < 215:
            thesis_parts.append(f"Lower-scoring game projected ({game_total} total)")

        # Check for scoring theme
        scoring_stats = ['points', 'threes', 'field_goals']
        scoring_count = sum(1 for s in stat_types if s in scoring_stats)
        if scoring_count >= 2:
            thesis_parts.append("Offensive-focused parlay targeting scoring production")

        # Check for rebounding theme
        if stat_types.count('rebounds') >= 2:
            thesis_parts.append("Glass-crashing play with correlated rebounding upside")

        # Check for playmaking theme
        if stat_types.count('assists') >= 2:
            thesis_parts.append("Playmaking correlation in expected high-possession game")

        # Check for PRA plays
        if 'points_rebounds_assists' in stat_types:
            thesis_parts.append("All-around production from high-usage players")

        # Check for team stack
        team_counts = defaultdict(int)
        for t in teams:
            team_counts[t] += 1
        stacked_team = max(team_counts.keys(), key=lambda x: team_counts[x]) if team_counts else None
        if stacked_team and team_counts[stacked_team] >= 2:
            thesis_parts.append(f"{stacked_team} team stack with correlated upside")

        # Add player-specific reasons
        top_reasons = []
        for leg in sorted(legs, key=lambda x: x.get('edge_pct', 0), reverse=True)[:2]:
            reason = leg.get('primary_reason', '')
            if reason and len(reason) > 10:
                top_reasons.append(reason)

        if not thesis_parts:
            thesis_parts.append(f"Multi-player SGP with {avg_edge:.1f}% average edge")

        # Combine into thesis
        thesis = ". ".join(thesis_parts[:2])
        if top_reasons:
            thesis += ". " + top_reasons[0]

        return thesis


# Singleton instance
_thesis_generator: Optional[ThesisGenerator] = None


def get_thesis_generator(use_llm: bool = True) -> ThesisGenerator:
    """Get singleton thesis generator instance."""
    global _thesis_generator
    if _thesis_generator is None:
        _thesis_generator = ThesisGenerator(use_llm=use_llm)
    return _thesis_generator


def generate_parlay_thesis(
    game_data: Dict,
    legs: List[Dict],
    use_llm: bool = True
) -> str:
    """
    Generate thesis for a parlay.

    Args:
        game_data: Game context dict
        legs: List of leg dicts
        use_llm: Whether to use LLM (default: True)

    Returns:
        Thesis string
    """
    generator = ThesisGenerator(use_llm=use_llm)
    return generator.generate_thesis(game_data, legs)
