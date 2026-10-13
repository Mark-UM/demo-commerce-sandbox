import json
import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.database import Store
from app.main import create_app
from app.seed import BASE_TIME, records

CUSTOM_TIME = datetime(2026, 10, 13, 6, tzinfo=UTC)
REPLY_PATH = "/api/support/inquiries/INQ-DEMO-002/replies"
COMMAND = {"text": "Recorded reply", "idempotency_key": "test-key"}


def reset_cli(path, *args):
    return subprocess.run(
        [sys.executable, "-m", "app.reset", *args],
        env={**os.environ, "SANDBOX_DB_PATH": str(path)},
        capture_output=True,
        text=True,
        timeout=15,
    )


def snapshot(store):
    with store.connect() as db:
        return db.execute("SELECT * FROM records ORDER BY rowid").fetchall()


def test_explicit_time_shifts_only_known_timestamps():
    def shifted_value(value):
        if isinstance(value, datetime):
            return value + (CUSTOM_TIME - BASE_TIME)
        if isinstance(value, list):
            return [shifted_value(item) for item in value]
        if isinstance(value, dict):
            return {key: shifted_value(item) for key, item in value.items()}
        return value

    original = list(records())
    shifted = list(records(CUSTOM_TIME))
    assert len(original) == len(shifted)
    for (kind, key, before), (new_kind, new_key, after) in zip(
        original, shifted, strict=True
    ):
        assert (kind, key) == (new_kind, new_key)
        expected = shifted_value(before.model_dump())
        assert after.model_dump() == expected


def test_custom_cli_reset_is_repeatable_and_survives_restart(tmp_path):
    path = tmp_path / "custom.sqlite3"
    result = reset_cli(path, "--base-time", "2026-10-13T06:00:00Z")
    assert result.returncode == 0, result.stderr
    assert "T0=2026-10-13T06:00:00Z" in result.stdout
    store = Store(str(path))
    before = snapshot(store)
    with TestClient(create_app(str(path))) as client:
        assert (
            client.get("/api/support/inquiries/INQ-DEMO-002").json()["created_at"]
            == "2026-10-13T06:00:00Z"
        )
        assert (
            client.get("/api/logistics/shipments/TRK-DEMO-002-1").json()["updated_at"]
            == "2026-10-13T05:50:00Z"
        )
        assert (
            client.get("/api/logistics/shipments/TRK-DEMO-007-1").json()["updated_at"]
            == "2026-10-10T06:00:00Z"
        )
        receipt = client.post(REPLY_PATH, json=COMMAND).json()
    with TestClient(create_app(str(path))) as restarted:
        assert restarted.post(REPLY_PATH, json=COMMAND).json() == receipt
        assert snapshot(store) == before
    result = reset_cli(path, "--base-time", "2026-10-13T06:00:00+00:00")
    assert result.returncode == 0, result.stderr
    assert snapshot(store) == before
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM replies").fetchone()[0] == 0
    result = reset_cli(path)
    assert result.returncode == 0, result.stderr
    assert snapshot(store) == [
        (kind, key, value.model_dump_json()) for kind, key, value in records()
    ]


@pytest.mark.parametrize(
    "invalid",
    [
        "garbage",
        "2026-10-13",
        "2026-10-13T06:00:00",
        "2026-10-13T14:00:00+08:00",
        "2026-02-30T06:00:00Z",
        "",
    ],
)
def test_invalid_cli_time_does_not_clear_existing_data(tmp_path, invalid):
    path = tmp_path / "existing.sqlite3"
    with TestClient(create_app(str(path))) as client:
        receipt = client.post(REPLY_PATH, json=COMMAND).json()
    store = Store(str(path))
    before = snapshot(store)
    result = reset_cli(path, "--base-time", invalid)
    assert result.returncode == 2
    assert "ISO 8601 UTC timestamp" in result.stderr
    assert snapshot(store) == before
    with store.connect() as db:
        saved = db.execute("SELECT receipt FROM replies").fetchone()[0]
    assert json.loads(saved) == receipt


def test_invalid_programmatic_time_preserves_data(tmp_path):
    store = Store(str(tmp_path / "existing.sqlite3"))
    store.initialize()
    before = snapshot(store)
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        store.initialize(reset=True, base_time=datetime(2026, 10, 13))
    assert snapshot(store) == before


def test_out_of_range_seed_time_preserves_data(tmp_path):
    store = Store(str(tmp_path / "existing.sqlite3"))
    store.initialize()
    before = snapshot(store)
    with pytest.raises(OverflowError):
        store.initialize(reset=True, base_time=datetime(1, 1, 1, tzinfo=UTC))
    assert snapshot(store) == before
