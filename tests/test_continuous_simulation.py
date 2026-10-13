from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from scripts.live_conversation import scenario


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "live.sqlite3"))) as client:
        yield client


def new_inquiry(client, key="customer-1"):
    payload = {"customer_message": "  Where is my order?\n", "idempotency_key": key}
    response = client.post("/api/support/inquiries", json=payload)
    assert response.status_code == 201
    return payload, response.json()


def test_complete_customer_and_source_progression(client):
    scenario(client)


def test_customer_ingress_is_exact_idempotent_and_concurrent(client):
    payload = {
        "customer_message": "原始消息\n  ",
        "order_id": None,
        "idempotency_key": "concurrent",
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda _: client.post("/api/support/inquiries", json=payload),
                range(16),
            )
        )
    assert all(row.status_code == 201 for row in responses)
    created = responses[0].json()
    assert all(row.json() == created for row in responses)
    assert created["customer_message"] == payload["customer_message"]
    assert created["order_id"] is None
    assert created["created_at"].endswith("Z")
    assert created["latest_customer_message_id"]
    assert client.get("/api/admin/summary").json()["inquiries"] == 61
    response = client.post(
        "/api/support/inquiries", json={**payload, "customer_message": "changed"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_followup_order_reference_and_old_retry_do_not_close_new_message(client):
    initial_command, inquiry = new_inquiry(client)
    path = f"/api/support/inquiries/{inquiry['inquiry_id']}"
    reply = {
        "text": "Please provide the order number.",
        "idempotency_key": "reply-1",
        "in_reply_to_message_id": inquiry["latest_customer_message_id"],
    }
    original = client.post(path + "/replies", json=reply).json()
    command = {
        "text": "It is ORD-DEMO-002.",
        "order_id": "ORD-DEMO-002",
        "idempotency_key": "followup",
    }
    customer = client.post(path + "/messages", json=command)
    assert customer.status_code == 201
    followup = customer.json()
    assert client.post(path + "/messages", json=command).json() == followup
    current = client.get(path).json()
    assert current["customer_message"] == command["text"]
    assert current["order_id"] == "ORD-DEMO-002"
    assert current["created_at"] == inquiry["created_at"]
    assert current["updated_at"] == followup["created_at"]
    assert current["latest_customer_message_id"] == followup["message_id"]
    assert current["status"] == "OPEN"
    assert client.post(path + "/replies", json=reply).json() == original
    assert client.get(path).json()["status"] == "OPEN"
    # Initial event retries also replay the original receipt, not a new message.
    assert client.post("/api/support/inquiries", json=initial_command).json() == inquiry
    assert len(client.get(path + "/messages").json()) == 3
    stale = client.post(path + "/replies", json={**reply, "idempotency_key": "stale"})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CUSTOMER_MESSAGE_CHANGED"
    changed_binding = client.post(
        path + "/replies",
        json={
            **reply,
            "in_reply_to_message_id": followup["message_id"],
        },
    )
    assert changed_binding.status_code == 409
    assert changed_binding.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(client.get(path + "/replies").json()) == 1
    with TestClient(create_app(client.app.state.store.path)) as restarted:
        assert restarted.get(path).json() == current
        assert len(restarted.get(path + "/messages").json()) == 3
    assert (
        client.post(
            path + "/replies",
            json={
                "text": "Carrier shows in transit.",
                "idempotency_key": "reply-2",
                "in_reply_to_message_id": followup["message_id"],
            },
        ).status_code
        == 200
    )
    assert client.get(path).json()["status"] == "REPLIED"
    assert (
        client.get(path + "/messages", params={"limit": 2, "offset": 2}).json()[0]
        == followup
    )


def test_customer_reference_omission_and_explicit_null_are_distinct(client):
    _, inquiry = new_inquiry(client)
    path = f"/api/support/inquiries/{inquiry['inquiry_id']}"
    first = {
        "text": "Order number",
        "idempotency_key": "one",
        "order_id": "ORD-DEMO-003",
    }
    assert client.post(path + "/messages", json=first).status_code == 201
    second = {"text": "Follow-up", "idempotency_key": "two"}
    assert client.post(path + "/messages", json=second).status_code == 201
    assert client.get(path).json()["order_id"] == "ORD-DEMO-003"
    assert (
        client.post(path + "/messages", json={**second, "order_id": None}).status_code
        == 409
    )
    assert (
        client.post(
            path + "/messages",
            json={**second, "idempotency_key": "three", "order_id": None},
        ).status_code
        == 201
    )
    assert client.get(path).json()["order_id"] is None


def test_followup_racing_with_a_bound_reply_remains_pending(client):
    _, inquiry = new_inquiry(client)
    path = f"/api/support/inquiries/{inquiry['inquiry_id']}"
    barrier = Barrier(2)

    def reply():
        barrier.wait(timeout=5)
        return client.post(
            path + "/replies",
            json={
                "text": "Answer to the first message",
                "idempotency_key": "race-reply",
                "in_reply_to_message_id": inquiry["latest_customer_message_id"],
            },
        )

    def followup():
        barrier.wait(timeout=5)
        return client.post(
            path + "/messages",
            json={
                "text": "New question",
                "idempotency_key": "race-customer",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        reply_future = pool.submit(reply)
        customer_future = pool.submit(followup)
        response, message = reply_future.result(), customer_future.result()
    assert response.status_code in (200, 409)
    assert message.status_code == 201
    current = client.get(path).json()
    assert current["status"] == "OPEN"
    assert current["customer_message"] == "New question"
    assert current["latest_customer_message_id"] == message.json()["message_id"]


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/support/inquiries", {"customer_message": " ", "idempotency_key": "k"}),
        ("/api/support/inquiries", {"customer_message": "Hello"}),
        (
            "/api/support/inquiries",
            {"customer_message": "Hello", "idempotency_key": " "},
        ),
        (
            "/api/support/inquiries",
            {"customer_message": "Hello", "idempotency_key": "k", "extra": True},
        ),
        (
            "/api/support/inquiries/INQ-DEMO-001/messages",
            {"text": "", "idempotency_key": "k"},
        ),
    ],
)
def test_invalid_incoming_messages_create_nothing(client, path, payload):
    assert client.post(path, json=payload).status_code == 422
    assert client.get("/api/admin/summary").json()["inquiries"] == 60
    assert len(client.get("/api/support/inquiries/INQ-DEMO-001/messages").json()) == 1


def test_unknown_thread_and_reset_clear_all_new_messages(client):
    assert (
        client.post(
            "/api/support/inquiries/missing/messages",
            json={
                "text": "Hello",
                "idempotency_key": "k",
            },
        ).status_code
        == 404
    )
    assert client.get("/api/support/inquiries/missing/messages").status_code == 404
    payload, inquiry = new_inquiry(client)
    path = f"/api/support/inquiries/{inquiry['inquiry_id']}"
    assert client.post("/api/admin/reset", json={}).status_code == 200
    assert client.get(path).status_code == 404
    assert (
        client.post("/api/support/inquiries", json=payload).json()["inquiry_id"]
        != inquiry["inquiry_id"]
    )


def test_source_updates_are_independent_and_preserve_nulls(client):
    parcel = {
        "parcel_id": "PAR-LIVE-1",
        "order_id": "ORD-DEMO-001",
        "carrier": None,
        "tracking_number": None,
        "updated_at": None,
    }
    path = "/api/admin/oms/orders/ORD-DEMO-001/parcels"
    assert client.post(path, json=parcel).status_code == 201
    assert client.post(path, json=parcel).status_code == 409
    tracking = {
        "carrier": "DemoExpress",
        "tracking_number": "TRK-LIVE-1",
        "updated_at": None,
    }
    assert (
        client.patch("/api/admin/oms/parcels/PAR-LIVE-1", json=tracking).status_code
        == 200
    )
    shipment = {
        "tracking_number": "TRK-LIVE-1",
        "parcel_id": "PAR-LIVE-1",
        "status": "NOT_COLLECTED",
        "updated_at": None,
    }
    assert (
        client.post("/api/admin/logistics/shipments", json=shipment).status_code == 201
    )
    event = {
        "event_id": "EVT-LIVE-1",
        "parcel_id": "PAR-LIVE-1",
        "status": "PICKED_UP",
        "description": "Collected.",
        "occurred_at": "2026-10-13T08:00:00+08:00",
        "updated_at": None,
    }
    added = client.post("/api/admin/logistics/shipments/TRK-LIVE-1/events", json=event)
    assert added.status_code == 201
    assert added.json()["occurred_at"] == "2026-10-13T00:00:00Z"
    assert added.json()["updated_at"] is None
    assert client.get("/api/logistics/shipments/TRK-LIVE-1").json() == shipment
    assert client.get("/api/oms/orders/ORD-DEMO-001").json()["status"] == "PAID"
    assert (
        client.patch(
            "/api/admin/logistics/shipments/TRK-LIVE-1",
            json={
                "status": "CUSTOM_UNKNOWN_STATUS",
                "updated_at": None,
            },
        ).json()["status"]
        == "CUSTOM_UNKNOWN_STATUS"
    )
    assert client.get("/api/oms/orders/ORD-DEMO-001").json()["status"] == "PAID"
    conflict = client.patch(
        "/api/admin/oms/parcels/PAR-LIVE-1",
        json={**tracking, "tracking_number": "changed"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "TRACKING_IMMUTABLE"
    assert (
        client.post(
            "/api/admin/logistics/shipments/TRK-LIVE-1/events", json=event
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/admin/logistics/shipments/TRK-LIVE-1/events",
            json={**event, "event_id": "different", "parcel_id": "wrong"},
        ).status_code
        == 409
    )
    assert len(client.get("/api/logistics/shipments/TRK-LIVE-1/events").json()) == 1
    assert client.post("/api/admin/reset", json={}).status_code == 200
    assert client.get("/api/logistics/shipments/TRK-LIVE-1").status_code == 404
    assert client.get("/api/oms/orders/ORD-DEMO-001/parcels").json() == []


def test_tracking_uniqueness_missing_references_and_validation(client):
    before = client.get("/api/admin/summary").json()
    parcel = {
        "parcel_id": "PAR-DUP",
        "order_id": "ORD-DEMO-001",
        "carrier": None,
        "tracking_number": "TRK-DEMO-002-1",
        "updated_at": None,
    }
    assert (
        client.post(
            "/api/admin/oms/orders/ORD-DEMO-001/parcels", json=parcel
        ).status_code
        == 409
    )
    assert (
        client.post("/api/admin/oms/orders/missing/parcels", json=parcel).status_code
        == 404
    )
    assert (
        client.post(
            "/api/admin/oms/orders/ORD-DEMO-003/parcels", json=parcel
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/admin/logistics/shipments",
            json={
                "tracking_number": "TRK-wrong",
                "parcel_id": "PAR-DEMO-002-1",
                "status": None,
                "updated_at": None,
            },
        ).status_code
        == 409
    )
    assert (
        client.patch(
            "/api/admin/oms/orders/missing", json={"status": "PAID", "updated_at": None}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            "/api/admin/oms/orders/ORD-DEMO-001",
            json={
                "status": "PAID",
                "updated_at": "2026-10-13T00:00:00",
            },
        ).status_code
        == 422
    )
    for timestamp in (1791849600, "1791849600", True):
        assert (
            client.patch(
                "/api/admin/oms/orders/ORD-DEMO-001",
                json={
                    "status": "PAID",
                    "updated_at": timestamp,
                },
            ).status_code
            == 422
        )
    assert client.get("/api/admin/summary").json() == before
