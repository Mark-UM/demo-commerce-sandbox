"""Verify a running local/container Sandbox over HTTP; --reset starts a new run."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import httpx


def check_source_facts(client):
    """Functional acceptance through independent source HTTP APIs only."""
    orders = {}
    for customer in range(1, 61):
        response = client.get(f"/api/oms/customers/CUS-DEMO-{customer:03}/orders")
        assert response.status_code == 200
        for order in response.json():
            assert order["customer_reference"] == f"CUS-DEMO-{customer:03}"
            orders[order["order_id"]] = order
    assert len(orders) == 120
    delivered = split = empty_history = unassigned = 0
    for order_id, order in orders.items():
        parcel_response = client.get(f"/api/oms/orders/{order_id}/parcels")
        assert parcel_response.status_code == 200
        parcels = parcel_response.json()
        assert sum(item["quantity"] for item in order["items"]) >= len(parcels), (
            order_id
        )
        split += len(parcels) > 1
        notes = client.get(f"/api/warehouse/orders/{order_id}/notes")
        assert notes.status_code == (503 if order_id == "ORD-DEMO-009" else 200)
        for parcel in parcels:
            assert parcel["order_id"] == order_id
            tracking = parcel["tracking_number"]
            if tracking is None:
                assert order["status"] == "PACKED"
                assert parcel["carrier"] is None
                unassigned += 1
                continue
            path = f"/api/logistics/shipments/{tracking}"
            shipment, events = client.get(path), client.get(path + "/events")
            expected = (
                504
                if order_id == "ORD-DEMO-008"
                else 404
                if order_id == "ORD-DEMO-010"
                else 200
            )
            assert shipment.status_code == events.status_code == expected, tracking
            if expected != 200:
                continue
            assert shipment.json()["parcel_id"] == parcel["parcel_id"]
            history = events.json()
            empty_history += not history
            for event in history:
                assert event["parcel_id"] == parcel["parcel_id"]
                assert event["occurred_at"] <= shipment.json()["updated_at"]
            if order["status"] == "DELIVERED":
                deliveries = [
                    datetime.fromisoformat(e["occurred_at"])
                    for e in history
                    if e["status"] == "DELIVERED"
                ]
                assert deliveries
                assert datetime.fromisoformat(order["updated_at"]) >= max(deliveries)
                delivered += 1
            if order_id == "ORD-DEMO-011":
                assert notes.json()[0]["created_at"] >= history[0]["occurred_at"]
                assert "not been handed" in notes.json()[0]["text"]
    assert unassigned == empty_history == 1
    unknown_reference = client.get("/api/support/inquiries/INQ-DEMO-107")
    assert unknown_reference.status_code == 200
    assert unknown_reference.json()["order_id"] is None
    print(
        f"Functional audit: 120 orders; {split} split orders; "
        f"{delivered} delivered parcels; source absence cases passed"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:9000")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument(
        "--receipt-file",
        type=Path,
        help="Save receipt and verify it on a later run after restart",
    )
    args = parser.parse_args()
    key = os.getenv("SANDBOX_API_KEY", "demo-commerce-key")
    with httpx.Client(
        base_url=args.base_url, timeout=10, headers={"X-API-Key": key}
    ) as client:
        assert client.get("/health").status_code == 200
        if args.reset:
            assert client.post("/api/admin/reset", json={}).status_code == 200
        summary = client.get("/api/admin/summary")
        assert summary.status_code == 200, summary.text
        assert summary.json()["orders"] == 120
        assert summary.json()["customers"] == 60
        assert client.get("/api/policy/order-support").status_code == 200
        check_source_facts(client)
        inquiries = []
        for offset in (0, 25, 50):
            response = client.get(
                "/api/support/inquiries", params={"limit": 25, "offset": offset}
            )
            assert response.status_code == 200
            inquiries.extend(response.json())
        assert len(inquiries) == len({row["inquiry_id"] for row in inquiries}) == 60
        path = "/api/support/inquiries/INQ-DEMO-101/replies"
        control = "/api/admin/scenarios/logistics/TRK-DEMO-101-1"
        if args.receipt_file and args.receipt_file.exists() and not args.reset:
            saved = json.loads(args.receipt_file.read_text(encoding="utf-8"))
            history = client.get(path).json()
            assert any(row["reply_id"] == saved["reply_id"] for row in history)
            states = client.get("/api/admin/scenarios").json()
            assert any(
                row["record_id"] == "TRK-DEMO-101-1"
                and row["mode"] == "TIMEOUT_ONCE"
                and row["remaining_failures"] == 0
                for row in states
            )
            print("Restart persistence: original receipt and consumed fault preserved")
        else:
            saved = None
        order = client.get("/api/oms/orders/ORD-DEMO-101").json()
        parcels = client.get(f"/api/oms/orders/{order['order_id']}/parcels").json()
        assert parcels
        assert client.put(control, json={"mode": "TIMEOUT_ONCE"}).status_code == 200
        shipment = "/api/logistics/shipments/TRK-DEMO-101-1"
        assert client.get(shipment).status_code == 504
        assert client.get(shipment).status_code == 200
        assert client.get(shipment + "/events").status_code == 200
        assert client.get("/api/warehouse/orders/ORD-DEMO-101/notes").status_code == 200
        command = {
            "text": "HTTP integration receipt.",
            "idempotency_key": "integration-v2",
        }
        response = client.post(path, json=command)
        assert response.status_code == 200
        receipt = response.json()
        if saved:
            assert receipt == saved
        assert client.post(path, json=command).json() == receipt
        assert any(
            row["reply_id"] == receipt["reply_id"] and row["text"] == command["text"]
            for row in client.get(path).json()
        )
        if args.receipt_file:
            args.receipt_file.write_text(json.dumps(receipt), encoding="utf-8")
        print(
            "Running Sandbox: full dataset, independent reads, retry and reply passed"
        )


if __name__ == "__main__":
    main()
