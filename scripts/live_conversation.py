"""Exercise a live conversation and fulfillment using source HTTP APIs only."""

import argparse
import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx


def scenario(client):
    suffix = uuid4().hex[:12]
    order_id, parcel_id, tracking = (
        f"ORD-LIVE-{suffix}",
        f"PAR-LIVE-{suffix}",
        f"TRK-LIVE-{suffix}",
    )

    def now():
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def send(method, path, body, status):
        response = client.request(method, path, json=body)
        assert response.status_code == status, (
            path,
            response.status_code,
            response.text,
        )
        return response.json()

    order = {
        "order_id": order_id,
        "customer_reference": "CUS-LIVE",
        "status": "PAID",
        "items": [{"sku": "DEMO-MUG", "product_name": "Travel mug", "quantity": 1}],
        "created_at": now(),
        "updated_at": None,
    }
    send("POST", "/api/admin/oms/orders", order, 201)
    incoming = {
        "customer_message": "When will my order ship?",
        "order_id": order_id,
        "idempotency_key": f"incoming-{suffix}",
    }
    inquiry = send("POST", "/api/support/inquiries", incoming, 201)
    assert send("POST", "/api/support/inquiries", incoming, 201) == inquiry
    path = f"/api/support/inquiries/{inquiry['inquiry_id']}"
    reply = {
        "text": "Packing is in progress.",
        "idempotency_key": "reply-1",
        "in_reply_to_message_id": inquiry["latest_customer_message_id"],
    }
    first_receipt = send("POST", path + "/replies", reply, 200)
    assert client.get(path).json()["status"] == "REPLIED"
    followup = {
        "text": "Has the carrier collected it yet?",
        "idempotency_key": "customer-2",
    }
    message = send("POST", path + "/messages", followup, 201)
    assert send("POST", path + "/messages", followup, 201) == message
    assert client.get(path).json()["status"] == "OPEN"
    assert send("POST", path + "/replies", reply, 200) == first_receipt
    assert client.get(path).json()["status"] == "OPEN"
    stale = client.post(
        path + "/replies", json={**reply, "idempotency_key": "stale-reply"}
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CUSTOMER_MESSAGE_CHANGED"
    send(
        "POST",
        f"/api/admin/oms/orders/{order_id}/parcels",
        {
            "parcel_id": parcel_id,
            "order_id": order_id,
            "carrier": None,
            "tracking_number": None,
            "updated_at": None,
        },
        201,
    )
    send(
        "PATCH",
        f"/api/admin/oms/parcels/{parcel_id}",
        {
            "carrier": "DemoExpress",
            "tracking_number": tracking,
            "updated_at": now(),
        },
        200,
    )
    send(
        "POST",
        "/api/admin/logistics/shipments",
        {
            "tracking_number": tracking,
            "parcel_id": parcel_id,
            "status": "NOT_COLLECTED",
            "updated_at": None,
        },
        201,
    )
    for index, status in enumerate(("PICKED_UP", "IN_TRANSIT", "DELIVERED")):
        timestamp = now()
        send(
            "POST",
            f"/api/admin/logistics/shipments/{tracking}/events",
            {
                "event_id": f"EVT-{suffix}-{index}",
                "parcel_id": parcel_id,
                "status": status,
                "description": f"Carrier reported {status}.",
                "occurred_at": timestamp,
                "updated_at": None,
            },
            201,
        )
        # Event ingestion does not implicitly rewrite either status record.
        send(
            "PATCH",
            f"/api/admin/logistics/shipments/{tracking}",
            {
                "status": status,
                "updated_at": timestamp,
            },
            200,
        )
        send(
            "PATCH",
            f"/api/admin/oms/orders/{order_id}",
            {
                "status": "DELIVERED" if status == "DELIVERED" else "SHIPPED",
                "updated_at": timestamp,
            },
            200,
        )
    send(
        "POST",
        f"/api/admin/warehouse/orders/{order_id}/notes",
        {
            "note_id": f"NOTE-{suffix}",
            "order_id": order_id,
            "text": "Packed and handed to the carrier.",
            "created_at": now(),
            "updated_at": None,
        },
        201,
    )
    assert client.get(f"/api/oms/orders/{order_id}").json()["status"] == "DELIVERED"
    assert (
        client.get(f"/api/logistics/shipments/{tracking}").json()["status"]
        == "DELIVERED"
    )
    assert len(client.get(f"/api/logistics/shipments/{tracking}/events").json()) == 3
    send(
        "POST",
        path + "/replies",
        {
            "text": "The carrier reports delivery.",
            "idempotency_key": "reply-2",
            "in_reply_to_message_id": message["message_id"],
        },
        200,
    )
    history = client.get(path + "/messages").json()
    assert [row["sender_type"] for row in history] == [
        "CUSTOMER",
        "SUPPORT",
        "CUSTOMER",
        "SUPPORT",
    ]
    assert history[0]["text"] == incoming["customer_message"]
    assert history[2]["text"] == followup["text"]
    assert client.get(path).json()["status"] == "REPLIED"
    assert (
        client.get(
            "/api/support/inquiries", params={"order_id": order_id, "status": "OPEN"}
        ).json()
        == []
    )
    print("Live workflow: customer follow-up, stale reply guard and delivery passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:9000")
    args = parser.parse_args()
    with httpx.Client(
        base_url=args.base_url,
        timeout=10,
        headers={"X-API-Key": os.getenv("SANDBOX_API_KEY", "demo-commerce-key")},
    ) as client:
        scenario(client)


if __name__ == "__main__":
    main()
