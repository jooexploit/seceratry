from assistant_app.main import format_snapshot_text


def test_snapshot_format_includes_score_and_goal():
    text = format_snapshot_text(
        {
            "now": "2026-03-04T12:05:12+02:00",
            "next_prayer": None,
            "prayer_streak": 0,
            "today_metrics": {
                "pomodoro_sessions": 0,
                "total_focus_minutes": 0,
                "water_reminders": 0,
                "stretch_reminders": 0,
                "eye_breaks": 0,
                "prayers_prayed": 0,
                "prayers_planned": 0,
            },
            "daily_score": {"total": 0},
            "quran_daily_goal": 1,
            "quran_daily_progress": {"done": 0},
            "active_mode": "workday",
        }
    )
    assert "Daily score:" in text
    assert "Quran daily goal:" in text
    assert "Mode:" in text
