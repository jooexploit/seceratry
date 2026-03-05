from assistant_app.runtime_state import SensitiveActionStore


def test_sensitive_action_store_roundtrip():
    store = SensitiveActionStore()
    token = store.create("shutdown|now", ttl_seconds=120)
    payload = store.consume(token)
    assert payload == "shutdown|now"
    assert store.consume(token) is None
