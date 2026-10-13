import pytest


@pytest.fixture(autouse=True)
def isolate_api_key(monkeypatch):
    """Behavior tests explicitly run without credentials; auth has its own tests."""
    monkeypatch.setenv("SANDBOX_API_KEY", "")
