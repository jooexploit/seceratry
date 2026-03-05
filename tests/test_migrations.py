import sqlite3

from assistant_app.migrations import apply_v2_migrations


def test_apply_v2_migrations_idempotent():
    conn = sqlite3.connect(":memory:")
    apply_v2_migrations(conn)
    apply_v2_migrations(conn)

    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row[0] for row in cur.fetchall()}
    assert "schema_migrations" in names
    assert "app_settings" in names
    assert "weekly_report_log" in names

    cur2 = conn.execute("SELECT version FROM schema_migrations WHERE version='v2_core'")
    row = cur2.fetchone()
    assert row is not None
