"""Verify a running local/container Sandbox over HTTP; --reset starts a new run."""

import argparse
import json
import os
from pathlib import Path

import httpx


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
