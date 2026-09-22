"""Fixed source data. No clock reads, random generation, or Product interpretation."""

from datetime import UTC, datetime, timedelta

from app.schemas import Event, Inquiry, Item, Note, Order, Parcel, Shipment

BASE_TIME = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)
SCENARIOS = {
    "S01": "normal order not yet shipped",
    "S02": "normal order in transit",
    "S03": "delivered order",
    "S04": "one order split into two parcels",
    "S05": "warehouse waiting for restock",
    "S06": "expected to ship today; not collected",
    "S07": "stale logistics information",
    "S08": "logistics API timeout/failure",
    "S09": "warehouse API failure",
    "S10": "order exists but no logistics record",
    "S11": "warehouse and logistics information conflict",
    "S12": "unknown/nonexistent order",
}


def records():
    """Yield (source collection, lookup key, validated payload)."""
    for n in range(1, 13):
        order_id = f"ORD-DEMO-{n:03}"
        inquiry_id = f"INQ-DEMO-{n:03}"
        yield (
            "inquiries",
            inquiry_id,
            Inquiry(
                inquiry_id=inquiry_id,
                order_id=order_id,
                customer_message=f"What is the status of my order {order_id}?",
                created_at=BASE_TIME,
            ),
        )
        if n == 12:
            continue
        status = {
            1: "PAID",
            3: "DELIVERED",
            4: "PARTIALLY_SHIPPED",
            5: "WAITING_STOCK",
            6: "PACKED",
            10: "PROCESSING",
        }.get(n, "SHIPPED")
        yield (
            "orders",
            order_id,
            Order(
                order_id=order_id,
                customer_reference=f"CUS-DEMO-{n:03}",
                status=status,
                items=[Item(sku="DEMO-MUG", product_name="Travel mug", quantity=1)]
                + (
                    [Item(sku="DEMO-BAG", product_name="Canvas bag", quantity=1)]
                    if n == 4
                    else []
                ),
                created_at=BASE_TIME - timedelta(days=5),
                updated_at=BASE_TIME - timedelta(minutes=30),
            ),
        )
        note_text = {
            1: "Payment received; awaiting packing.",
            5: "Travel mug out of stock; waiting for restock.",
            6: "Expected to ship today, subject to carrier collection.",
            10: "Packing complete; awaiting logistics registration.",
            11: "Parcel has not been handed to the carrier today.",
        }.get(n, "Packing completed.")
        yield (
            "notes",
            order_id,
            Note(
                note_id=f"NOTE-DEMO-{n:03}",
                order_id=order_id,
                text=note_text,
                created_at=BASE_TIME - timedelta(minutes=20),
                updated_at=None if n == 5 else BASE_TIME - timedelta(minutes=20),
            ),
        )
        if n in (1, 5):
            continue
        for p in range(1, 3 if n == 4 else 2):
            parcel_id = f"PAR-DEMO-{n:03}-{p}"
            tracking = f"TRK-DEMO-{n:03}-{p}"
            yield (
                "parcels",
                order_id,
                Parcel(
                    parcel_id=parcel_id,
                    order_id=order_id,
                    carrier="DemoExpress",
                    tracking_number=tracking,
                    updated_at=None,
                ),
            )
            if n == 10:
                continue
            shipment_status = (
                "DELIVERED"
                if n == 3
                else "NOT_COLLECTED"
                if n == 6 or (n == 4 and p == 2)
                else "PICKED_UP"
                if n == 11
                else "IN_TRANSIT"
            )
            updated = BASE_TIME - (
                timedelta(hours=72) if n == 7 else timedelta(minutes=10)
            )
            yield (
                "shipments",
                tracking,
                Shipment(
                    tracking_number=tracking,
                    parcel_id=parcel_id,
                    status=shipment_status,
                    updated_at=updated,
                ),
            )
            statuses = (
                ["LABEL_CREATED"]
                if shipment_status == "NOT_COLLECTED"
                else ["PICKED_UP"]
                if n == 11
                else ["PICKED_UP", shipment_status]
            )
            for index, event_status in enumerate(statuses):
                yield (
                    "events",
                    tracking,
                    Event(
                        event_id=f"EVT-DEMO-{n:03}-{p}-{index + 1}",
                        parcel_id=parcel_id,
                        status=event_status,
                        description={
                            "LABEL_CREATED": (
                                "Shipping label created; awaiting collection."
                            ),
                            "PICKED_UP": "Collected by carrier.",
                            "IN_TRANSIT": "Departed sorting facility.",
                            "DELIVERED": "Delivered to recipient.",
                        }[event_status],
                        occurred_at=updated
                        - timedelta(hours=len(statuses) - index - 1),
                        updated_at=None,
                    ),
                )
