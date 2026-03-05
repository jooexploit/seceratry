from assistant_app.services.scoring import calculate_daily_score


def test_score_bounds():
    payload = calculate_daily_score(
        {
            "total_focus_minutes": 400,
            "pomodoro_sessions": 8,
            "prayers_planned": 5,
            "prayers_prayed": 5,
            "water_reminders": 4,
            "stretch_reminders": 4,
            "eye_breaks": 4,
        },
        prayer_streak=9,
    )
    assert 0 <= payload.total <= 100
    assert payload.total >= 80


def test_score_zero_case():
    payload = calculate_daily_score({}, prayer_streak=0)
    assert payload.total >= 0
