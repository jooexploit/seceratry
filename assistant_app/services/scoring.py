from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class ScoreBreakdown:
    total: int
    focus: int
    prayers: int
    health: int
    consistency: int


def calculate_daily_score(metrics: Dict[str, int], prayer_streak: int) -> ScoreBreakdown:
    focus_minutes = int(metrics.get("total_focus_minutes", 0) or 0)
    pomodoro = int(metrics.get("pomodoro_sessions", 0) or 0)
    prayed = int(metrics.get("prayers_prayed", 0) or 0)
    planned = int(metrics.get("prayers_planned", 0) or 0)
    water = int(metrics.get("water_reminders", 0) or 0)
    stretch = int(metrics.get("stretch_reminders", 0) or 0)
    eye = int(metrics.get("eye_breaks", 0) or 0)

    focus_score = min(35, int(focus_minutes / 8) + min(10, pomodoro * 2))
    prayer_ratio = 1.0 if planned <= 0 else max(0.0, min(1.0, prayed / planned))
    prayers_score = int(round(prayer_ratio * 35))
    health_score = min(20, water * 2 + stretch * 2 + eye * 2)
    consistency = min(10, prayer_streak)

    total = max(0, min(100, focus_score + prayers_score + health_score + consistency))
    return ScoreBreakdown(total=total, focus=focus_score, prayers=prayers_score, health=health_score, consistency=consistency)


def format_score_text(score: ScoreBreakdown) -> str:
    return (
        f"Daily score: {score.total}/100\n"
        f"- Focus: {score.focus}\n"
        f"- Prayers: {score.prayers}\n"
        f"- Health: {score.health}\n"
        f"- Consistency: {score.consistency}"
    )
