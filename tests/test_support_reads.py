import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "support.sqlite3"))) as client:
        yield client


def test_inquiry_discovery_pagination_and_filter(client):
    path = "/api/support/inquiries"
    result = client.get(path)
    assert result.status_code == 200
    all_rows = result.json()
    assert [row["inquiry_id"] for row in all_rows] == [
        f"INQ-DEMO-{n:03}" for n in range(1, 13)
    ]
    pages = [
        client.get(path, params={"limit": 5, "offset": offset}).json()
        for offset in (0, 5, 10)
    ]
    assert sum(pages, []) == all_rows
    assert client.get(path, params={"offset": 12}).json() == []
    for row in all_rows:
        assert client.get(f"{path}/{row['inquiry_id']}").json() == row
    assert client.get(path, params={"order_id": "ORD-DEMO-004"}).json() == [all_rows[3]]
    # Discovery reports source inquiries, including the absent-order scenario.
    assert client.get(path, params={"order_id": "ORD-DEMO-012"}).json() == [
        all_rows[11]
    ]
    assert client.get(path, params={"order_id": "missing"}).json() == []
    assert (
        client.get(path, params={"order_id": "ORD-DEMO-004", "offset": 1}).json() == []
    )


def test_reply_history_preserves_exact_text_deduplicates_and_isolates(client):
    path = "/api/support/inquiries/INQ-DEMO-004/replies"
    assert client.get(path).json() == []
    text = "  First line.\n第二行。  "
    first_command = {"text": text, "idempotency_key": "first"}
    first = client.post(path, json=first_command).json()
    assert client.post(path, json=first_command).json() == first
    assert (
        client.post(path, json={**first_command, "text": "changed"}).status_code == 409
    )
    second_command = {"text": "Second", "idempotency_key": "second"}
    second = client.post(path, json=second_command).json()
    expected = [
        {**first, **first_command, "inquiry_id": "INQ-DEMO-004"},
        {**second, **second_command, "inquiry_id": "INQ-DEMO-004"},
    ]
    assert client.get(path).status_code == 200
    assert client.get(path).json() == expected
    assert client.get(path, params={"limit": 1}).json() == expected[:1]
    assert client.get(path, params={"limit": 1, "offset": 1}).json() == expected[1:]
    assert client.get(path, params={"offset": 2}).json() == []
    assert client.get(path.replace("004", "003")).json() == []
    with TestClient(create_app(client.app.state.store.path)) as restarted:
        assert restarted.get(path).json() == expected
    client.app.state.store.initialize(reset=True)
    assert client.get(path).json() == []
    assert len(client.get("/api/support/inquiries").json()) == 12


@pytest.mark.parametrize(
    "path",
    [
        "/api/support/inquiries",
        "/api/support/inquiries/INQ-DEMO-001/replies",
    ],
)
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"limit": "wrong"},
    ],
)
def test_pagination_validation(client, path, params):
    response = client.get(path, params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_inquiry_history_is_not_an_empty_success(client):
    result = client.get("/api/support/inquiries/missing/replies")
    assert result.status_code == 404
    assert result.json()["error"]["code"] == "INQUIRY_NOT_FOUND"
    assert (
        client.get("/api/support/inquiries", params={"order_id": ""}).status_code == 422
    )
