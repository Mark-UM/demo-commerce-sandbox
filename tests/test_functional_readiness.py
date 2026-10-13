from collections import defaultdict

from fastapi.testclient import TestClient

from app.main import create_app
from app.seed import records


def fixture_data():
    result = defaultdict(lambda: defaultdict(list))
    for kind, key, value in records():
        result[kind][key].append(value)
    return result


def test_delivered_orders_do_not_claim_delivery_before_source_event():
    data = fixture_data()
    for order_id, orders in data["orders"].items():
        order = orders[0]
        if order.status != "DELIVERED":
            continue
        for parcel in data["parcels"][order_id]:
            delivery = [
                event
                for event in data["events"][parcel.tracking_number]
                if event.status == "DELIVERED"
            ]
            assert delivery
            assert order.updated_at >= max(event.occurred_at for event in delivery), (
                order_id
            )


def test_s11_is_a_conflict_not_a_normal_later_pickup():
    data = fixture_data()
    note = data["notes"]["ORD-DEMO-011"][0]
    pickup = data["events"]["TRK-DEMO-011-1"][0]
    assert "not been handed" in note.text
    assert pickup.status == "PICKED_UP"
    # A note recorded BEFORE pickup could simply describe a later normal pickup.
    assert note.created_at >= pickup.occurred_at


def test_split_orders_have_enough_physical_items_for_their_parcels():
    data = fixture_data()
    for order_id, parcels in data["parcels"].items():
        quantity = sum(item.quantity for item in data["orders"][order_id][0].items)
        assert quantity >= len(parcels), order_id


def test_pending_inquiries_stop_including_an_accepted_reply(tmp_path):
    with TestClient(create_app(str(tmp_path / "pending.sqlite3"))) as client:
        path = "/api/support/inquiries"
        inquiry_id = "INQ-DEMO-002"
        command = {"text": "Accepted reply", "idempotency_key": "pending-test"}
        receipt = client.post(f"{path}/{inquiry_id}/replies", json=command)
        assert receipt.status_code == 200
        pending = client.get(path, params={"status": "OPEN", "limit": 100})
        assert pending.status_code == 200
        assert inquiry_id not in {row["inquiry_id"] for row in pending.json()}
        replied = client.get(path, params={"status": "REPLIED", "limit": 100})
        assert [row["inquiry_id"] for row in replied.json()] == [inquiry_id]
        assert client.get(f"{path}/{inquiry_id}").json()["status"] == "REPLIED"
        assert (
            client.post(f"{path}/{inquiry_id}/replies", json=command).json()
            == receipt.json()
        )
        assert (
            len(client.get(path, params={"status": "OPEN", "limit": 100}).json()) == 59
        )
        assert client.get(path, params={"status": "REPLIED", "offset": 1}).json() == []
        assert client.get(path, params={"status": "INVALID"}).status_code == 422
        with TestClient(create_app(client.app.state.store.path)) as restarted:
            assert (
                restarted.get(path, params={"status": "REPLIED"}).json()
                == replied.json()
            )
        assert client.post("/api/admin/reset", json={}).status_code == 200
        assert client.get(path, params={"status": "REPLIED"}).json() == []
        assert (
            len(client.get(path, params={"status": "OPEN", "limit": 100}).json()) == 60
        )


def test_source_absence_cases_are_reachable_without_editing_database(tmp_path):
    with TestClient(create_app(str(tmp_path / "absence.sqlite3"))) as client:
        inquiry = client.get("/api/support/inquiries/INQ-DEMO-107")
        assert inquiry.status_code == 200
        assert inquiry.json()["order_id"] is None
        parcel = client.get("/api/oms/orders/ORD-DEMO-110/parcels")
        assert parcel.status_code == 200
        assert len(parcel.json()) == 1
        assert parcel.json()[0]["tracking_number"] is None
        assert parcel.json()[0]["carrier"] is None
        shipment = client.get("/api/logistics/shipments/TRK-DEMO-113-1")
        assert shipment.status_code == 200
        assert shipment.json()["status"] == "IN_TRANSIT"
        assert shipment.json()["updated_at"] is not None
        events = client.get("/api/logistics/shipments/TRK-DEMO-113-1/events")
        assert events.status_code == 200
        assert events.json() == []
