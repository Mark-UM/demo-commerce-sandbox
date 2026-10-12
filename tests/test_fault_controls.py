from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "faults.sqlite3"))) as client:
        yield client


@pytest.mark.parametrize(
    "system,record,path",
    [
        ("logistics", "TRK-DEMO-002-1", "/api/logistics/shipments/TRK-DEMO-002-1"),
        ("warehouse", "ORD-DEMO-002", "/api/warehouse/orders/ORD-DEMO-002/notes"),
    ],
)
@pytest.mark.parametrize(
    "mode,status,code",
    [
        ("ALWAYS_TIMEOUT", 504, "TEMPORARILY_UNAVAILABLE"),
        ("HTTP_500", 500, "SCENARIO_FORCED_FAILURE"),
        ("HTTP_429", 429, "RATE_LIMITED"),
    ],
)
def test_independent_persistent_failures(
    client, system, record, path, mode, status, code
):
    control = f"/api/admin/scenarios/{system}/{record}"
    before = client.get(path).json()
    assert client.put(control, json={"mode": mode}).status_code == 200
    for _ in range(2):
        response = client.get(path, headers={"X-Request-Id": "fault-test"})
        assert response.status_code == status
        assert response.json()["error"]["code"].endswith(code)
        assert response.json()["error"]["request_id"] == "fault-test"
        if status == 429:
            assert response.headers["Retry-After"] == "1"
    assert client.get("/api/oms/orders/ORD-DEMO-002").status_code == 200
    assert client.get("/api/support/inquiries/INQ-DEMO-002").status_code == 200
    other = (
        "/api/warehouse/orders/ORD-DEMO-002/notes"
        if system == "logistics"
        else "/api/logistics/shipments/TRK-DEMO-002-1"
    )
    assert client.get(other).status_code == 200
    assert client.delete(control).status_code == 204
    assert client.get(path).json() == before
    assert client.get("/api/admin/scenarios").json() == []


def test_only_one_parcel_fails_and_reply_still_works(client):
    parcels = client.get("/api/oms/orders/ORD-DEMO-004/parcels").json()
    tracking = parcels[0]["tracking_number"]
    client.put(f"/api/admin/scenarios/logistics/{tracking}", json={"mode": "HTTP_500"})
    assert client.get(f"/api/logistics/shipments/{tracking}").status_code == 500
    assert client.get(f"/api/logistics/shipments/{tracking}/events").status_code == 500
    second = client.get(f"/api/logistics/shipments/{parcels[1]['tracking_number']}")
    assert second.status_code == 200
    assert second.json()["status"] == "NOT_COLLECTED"
    command = {"text": "Exact supplied reply", "idempotency_key": "partial-case"}
    path = "/api/support/inquiries/INQ-DEMO-004/replies"
    reply = client.post(path, json=command)
    assert reply.status_code == 200
    assert client.post(path, json=command).json() == reply.json()


def test_one_shot_is_shared_by_details_events_and_persists(client):
    control = "/api/admin/scenarios/logistics/TRK-DEMO-008-1"
    details = "/api/logistics/shipments/TRK-DEMO-008-1"
    client.put(control, json={"mode": "TIMEOUT_ONCE"})
    assert client.get(details + "/events").status_code == 504
    assert client.get(details).status_code == 200
    assert client.get(details + "/events").status_code == 200
    assert client.get("/api/admin/scenarios").json()[0]["remaining_failures"] == 0
    with TestClient(create_app(client.app.state.store.path)) as restarted:
        assert restarted.get(details).status_code == 200
    client.put(control, json={"mode": "TIMEOUT_ONCE"})
    assert client.get(details).status_code == 504
    assert client.get(details).status_code == 200
    client.delete(control)
    assert client.get(details).status_code == 504  # Restore the golden S08 default.


def test_concurrent_requests_consume_one_failure(client):
    control = "/api/admin/scenarios/logistics/TRK-DEMO-002-1"
    client.put(control, json={"mode": "TIMEOUT_ONCE"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(
            pool.map(
                lambda _: (
                    client.get("/api/logistics/shipments/TRK-DEMO-002-1").status_code
                ),
                range(16),
            )
        )
    assert statuses.count(504) == 1
    assert statuses.count(200) == 15


def test_normal_override_restart_and_reset(client):
    control = "/api/admin/scenarios/warehouse/ORD-DEMO-009"
    path = "/api/warehouse/orders/ORD-DEMO-009/notes"
    client.put(control, json={"mode": "NORMAL"})
    assert client.get(path).status_code == 200
    with TestClient(create_app(client.app.state.store.path)) as restarted:
        assert restarted.get(path).status_code == 200
        assert restarted.get("/api/admin/scenarios").json()[0]["mode"] == "NORMAL"
    client.app.state.store.initialize(reset=True)
    assert client.get("/api/admin/scenarios").json() == []
    assert client.get(path).status_code == 503


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "UNKNOWN"},
        {"mode": "SLOW_RESPONSE"},
        {"mode": "SLOW_RESPONSE", "delay_ms": -1},
        {"mode": "SLOW_RESPONSE", "delay_ms": 10001},
        {"mode": "SLOW_RESPONSE", "delay_ms": True},
        {"mode": "HTTP_500", "delay_ms": 100},
        {"mode": "NORMAL", "extra": True},
    ],
)
def test_invalid_controls_do_not_replace_previous_rule(client, body):
    control = "/api/admin/scenarios/logistics/TRK-DEMO-002-1"
    original = client.put(control, json={"mode": "NORMAL"}).json()
    assert client.put(control, json=body).status_code == 422
    assert client.get("/api/admin/scenarios").json() == [original]


def test_unknown_targets_cannot_be_created(client):
    for system in ("logistics", "warehouse"):
        assert (
            client.put(
                f"/api/admin/scenarios/{system}/missing", json={"mode": "HTTP_500"}
            ).status_code
            == 404
        )
    assert (
        client.put(
            "/api/admin/scenarios/oms/ORD-DEMO-002", json={"mode": "HTTP_500"}
        ).status_code
        == 422
    )
    assert client.get("/api/admin/scenarios").json() == []
