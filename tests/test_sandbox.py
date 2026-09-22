from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.seed import BASE_TIME, SCENARIOS


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "test.sqlite3"))) as client:
        yield client


def test_health(client):
    assert client.get("/health").json() == {
        "status": "ok",
        "database": "ok",
        "seed_version": "s0-s1-v1",
    }


@pytest.mark.parametrize("n", range(1, 13))
def test_all_scenarios(client, n):
    order = f"ORD-DEMO-{n:03}"
    inquiry = client.get(f"/api/support/inquiries/INQ-DEMO-{n:03}")
    assert inquiry.status_code == 200
    assert inquiry.json()["order_id"] == order
    assert order in inquiry.json()["customer_message"]
    result = client.get(f"/api/oms/orders/{order}")
    if n == 12:
        assert result.status_code == 404
        assert result.json()["error"]["code"] == "ORDER_NOT_FOUND"
        return
    assert result.status_code == 200
    assert result.json()["order_id"] == order
    assert result.json()["items"][0] == {
        "sku": "DEMO-MUG",
        "product_name": "Travel mug",
        "quantity": 1,
    }
    parcels = client.get(f"/api/oms/orders/{order}/parcels")
    assert parcels.status_code == 200
    assert len(parcels.json()) == (0 if n in (1, 5) else 2 if n == 4 else 1)
    for parcel in parcels.json():
        assert parcel["order_id"] == order
        assert parcel["updated_at"] is None
        path = f"/api/logistics/shipments/{parcel['tracking_number']}"
        shipment, events = client.get(path), client.get(path + "/events")
        expected = 504 if n == 8 else 404 if n == 10 else 200
        assert shipment.status_code == events.status_code == expected
        if expected == 200:
            assert shipment.json()["parcel_id"] == parcel["parcel_id"]
            assert all(e["parcel_id"] == parcel["parcel_id"] for e in events.json())
            assert all(e["updated_at"] is None for e in events.json())
            assert events.json()
    notes = client.get(f"/api/warehouse/orders/{order}/notes")
    assert notes.status_code == (503 if n == 9 else 200)
    if n != 9:
        assert notes.json()[0]["order_id"] == order
        assert notes.json()[0]["text"]


def test_distinct_scenario_facts(client):
    def shipment(n, p=1):
        return client.get(f"/api/logistics/shipments/TRK-DEMO-{n:03}-{p}").json()

    def note(n):
        return client.get(f"/api/warehouse/orders/ORD-DEMO-{n:03}/notes").json()[0]

    assert shipment(2)["status"] == "IN_TRANSIT"
    assert shipment(3)["status"] == "DELIVERED"
    assert shipment(4)["status"] == "IN_TRANSIT"
    assert shipment(4, 2)["status"] == "NOT_COLLECTED"
    assert "waiting for restock" in note(5)["text"]
    assert note(5)["updated_at"] is None
    assert "Expected to ship today" in note(6)["text"]
    assert shipment(6)["status"] == "NOT_COLLECTED"
    assert "not been handed" in note(11)["text"]
    assert shipment(11)["status"] == "PICKED_UP"
    assert shipment(7)["updated_at"] == (
        BASE_TIME - timedelta(hours=72)
    ).isoformat().replace("+00:00", "Z")
    assert client.get("/api/oms/orders/ORD-DEMO-001").json()["status"] == "PAID"
    assert len(client.get("/api/oms/orders/ORD-DEMO-004").json()["items"]) == 2


@pytest.mark.parametrize(
    "path,code,status",
    [
        ("/api/oms/orders/ORD-DEMO-012", "ORDER_NOT_FOUND", 404),
        ("/api/oms/orders/ORD-DEMO-012/parcels", "ORDER_NOT_FOUND", 404),
        ("/api/warehouse/orders/ORD-DEMO-012/notes", "ORDER_NOT_FOUND", 404),
        ("/api/logistics/shipments/missing", "SHIPMENT_NOT_FOUND", 404),
        ("/api/support/inquiries/missing", "INQUIRY_NOT_FOUND", 404),
        (
            "/api/logistics/shipments/TRK-DEMO-008-1",
            "LOGISTICS_TEMPORARILY_UNAVAILABLE",
            504,
        ),
        (
            "/api/warehouse/orders/ORD-DEMO-009/notes",
            "WAREHOUSE_TEMPORARILY_UNAVAILABLE",
            503,
        ),
    ],
)
def test_error_contract(client, path, code, status):
    response = client.get(path, headers={"X-Request-Id": "test-request"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"]
    assert response.json()["error"]["request_id"] == "test-request"
    assert response.headers["X-Request-Id"] == "test-request"


REPLY_PATH = "/api/support/inquiries/INQ-DEMO-002/replies"


def test_reply_idempotency(client):
    command = {"text": " Your parcel is in transit. ", "idempotency_key": "key-1"}
    original = client.post(REPLY_PATH, json=command)
    assert original.status_code == 200
    assert original.json()["status"] == "SENT"
    assert original.json()["sent_at"].endswith("Z")
    assert client.post(REPLY_PATH, json=command).json() == original.json()
    conflict = client.post(REPLY_PATH, json={**command, "text": "Changed"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    different = client.post(REPLY_PATH, json={**command, "idempotency_key": "key-2"})
    assert different.status_code == 200
    assert different.json()["reply_id"] != original.json()["reply_id"]
    with client.app.state.store.connect() as db:
        rows = db.execute("SELECT text FROM replies").fetchall()
    assert rows == [(command["text"],), (command["text"],)]
    other = client.post(REPLY_PATH.replace("002", "003"), json=command)
    assert other.status_code == 200
    assert other.json()["reply_id"] != original.json()["reply_id"]


def test_concurrent_retries(client):
    def send(_):
        return client.post(
            REPLY_PATH, json={"text": "Exact text", "idempotency_key": "race"}
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send, range(16)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["reply_id"] for r in responses}) == 1
    with client.app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM replies").fetchone()[0] == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": "", "idempotency_key": "k"},
        {"text": "hello", "idempotency_key": " "},
        {"text": " ", "idempotency_key": "k"},
        {"text": "hello", "idempotency_key": "k", "unexpected": True},
    ],
)
def test_invalid_reply(client, body):
    assert client.post(REPLY_PATH, json=body).status_code == 422


def test_missing_reply_target(client):
    response = client.post(
        REPLY_PATH.replace("002", "missing"),
        json={"text": "Hello", "idempotency_key": "k"},
    )
    assert response.status_code == 404
    with client.app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM replies").fetchone()[0] == 0


def test_reset_persistence_and_timestamps(client):
    store = client.app.state.store
    with store.connect() as db:
        before = db.execute("SELECT * FROM records ORDER BY rowid").fetchall()
    assert len(SCENARIOS) == 12
    for _, _, payload in before:
        assert "fetched_at" not in payload
        assert "freshness" not in payload
    command = {"text": "Recorded", "idempotency_key": "persist"}
    original = client.post(REPLY_PATH, json=command).json()
    with TestClient(create_app(store.path)) as restarted:
        assert restarted.post(REPLY_PATH, json=command).json() == original
    store.initialize(reset=True)
    with store.connect() as db:
        assert db.execute("SELECT * FROM records ORDER BY rowid").fetchall() == before
        assert db.execute("SELECT count(*) FROM replies").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT count(*) FROM records WHERE collection='orders'"
            ).fetchone()[0]
            == 11
        )
    assert (
        client.post(REPLY_PATH, json=command).json()["reply_id"] != original["reply_id"]
    )
    assert client.get("/api/logistics/shipments/TRK-DEMO-008-1").status_code == 504


def test_openapi_contract(client):
    document = client.get("/openapi.json").json()
    assert len(document["paths"]) == 8
    assert "fetched_at" not in str(document)
    order = client.get("/api/oms/orders/ORD-DEMO-002").json()
    assert set(order) == {
        "order_id",
        "customer_reference",
        "status",
        "items",
        "created_at",
        "updated_at",
    }
    assert order["created_at"] == "2026-09-15T06:00:00Z"
    assert order["updated_at"] == "2026-09-20T05:30:00Z"
