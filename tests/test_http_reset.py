import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REPLY_PATH = "/api/support/inquiries/INQ-DEMO-004/replies"
COMMAND = {"text": "Reply before reset", "idempotency_key": "same-key"}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "reset.sqlite3"))) as client:
        yield client


def populate(client):
    receipt = client.post(REPLY_PATH, json=COMMAND).json()
    assert (
        client.put(
            "/api/admin/scenarios/logistics/TRK-DEMO-008-1", json={"mode": "NORMAL"}
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/admin/scenarios/warehouse/ORD-DEMO-009", json={"mode": "TIMEOUT_ONCE"}
        ).status_code
        == 200
    )
    assert client.get("/api/warehouse/orders/ORD-DEMO-009/notes").status_code == 504
    assert client.get("/api/warehouse/orders/ORD-DEMO-009/notes").status_code == 200
    return receipt


def test_running_service_reset_restores_defaults_and_starts_new_reply_run(client):
    original_inquiries = client.get("/api/support/inquiries").json()
    receipt = populate(client)
    response = client.post("/api/admin/reset", json={})
    assert response.status_code == 200
    assert response.json() == {
        "status": "RESET",
        "seed_version": "s0-s1-v1",
        "base_time": "2026-09-20T06:00:00Z",
    }
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/admin/scenarios").json() == []
    assert client.get(REPLY_PATH).json() == []
    assert client.get("/api/support/inquiries").json() == original_inquiries
    assert client.get("/api/logistics/shipments/TRK-DEMO-008-1").status_code == 504
    assert client.get("/api/warehouse/orders/ORD-DEMO-009/notes").status_code == 503
    assert client.get("/api/oms/orders/ORD-DEMO-012").status_code == 404
    assert len(client.get("/api/oms/orders/ORD-DEMO-004/parcels").json()) == 2
    new_receipt = client.post(REPLY_PATH, json=COMMAND).json()
    assert new_receipt["reply_id"] != receipt["reply_id"]
    assert client.post(REPLY_PATH, json=COMMAND).json() == new_receipt


def test_http_reset_custom_time_is_repeatable_and_persistent(client):
    payload = {"base_time": "2026-10-13T06:00:00+00:00"}
    assert (
        client.post("/api/admin/reset", json=payload).json()["base_time"]
        == "2026-10-13T06:00:00Z"
    )
    order_path = "/api/oms/orders/ORD-DEMO-004"
    order = client.get(order_path).json()
    assert order["updated_at"] == "2026-10-13T05:30:00Z"
    assert (
        client.get("/api/logistics/shipments/TRK-DEMO-007-1").json()["updated_at"]
        == "2026-10-10T06:00:00Z"
    )
    assert (
        client.get("/api/oms/orders/ORD-DEMO-004/parcels").json()[0]["updated_at"]
        is None
    )
    assert client.post("/api/admin/reset", json=payload).status_code == 200
    assert client.get(order_path).json() == order
    with TestClient(create_app(client.app.state.store.path)) as restarted:
        assert restarted.get(order_path).json() == order
    assert client.post("/api/admin/reset", json={}).status_code == 200
    assert client.get(order_path).json()["updated_at"] == "2026-09-20T05:30:00Z"


@pytest.mark.parametrize(
    "payload",
    [
        {"base_time": "invalid"},
        {"base_time": "2026-10-13T06:00:00"},
        {"base_time": "2026-10-13T14:00:00+08:00"},
        {"base_time": "0001-01-01T00:00:00Z"},
        {"base_time": 1791871200},
        {"base_time": True},
        {"extra": True},
    ],
)
def test_invalid_reset_preserves_reply_and_fault_state(client, payload):
    receipt = populate(client)
    faults = client.get("/api/admin/scenarios").json()
    response = client.post("/api/admin/reset", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert client.get("/api/admin/scenarios").json() == faults
    assert client.get(REPLY_PATH).json()[0]["reply_id"] == receipt["reply_id"]


def test_failed_seed_insertion_rolls_back_reset(client, monkeypatch):
    receipt = populate(client)
    faults = client.get("/api/admin/scenarios").json()
    original_connect = client.app.state.store.connect

    # Fail after DELETE has run, exercising transaction rollback, not validation.
    from contextlib import contextmanager

    @contextmanager
    def failing_connect():
        with original_connect() as db:

            class FailingConnection:
                def execute(self, *args):
                    return db.execute(*args)

                def executemany(self, *args):
                    raise RuntimeError("Injected insert failure")

            yield FailingConnection()

    with monkeypatch.context() as patch:
        patch.setattr(client.app.state.store, "connect", failing_connect)
        with pytest.raises(RuntimeError, match="Injected insert failure"):
            client.post("/api/admin/reset", json={})
    assert client.get("/api/admin/scenarios").json() == faults
    assert client.get(REPLY_PATH).json()[0]["reply_id"] == receipt["reply_id"]
    assert len(client.get("/api/support/inquiries").json()) == 12
