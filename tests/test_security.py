import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(str(tmp_path / "auth.sqlite3"), api_key="test-key")
    ) as client:
        yield client


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/oms/orders/ORD-DEMO-002", None),
        ("GET", "/api/logistics/shipments/TRK-DEMO-002-1", None),
        ("GET", "/api/warehouse/orders/ORD-DEMO-002/notes", None),
        ("GET", "/api/support/inquiries", None),
        ("GET", "/api/policy/order-support", None),
        ("GET", "/api/admin/summary", None),
        ("POST", "/api/admin/reset", {}),
        ("PUT", "/api/admin/scenarios/logistics/TRK-DEMO-002-1", {"mode": "NORMAL"}),
        (
            "POST",
            "/api/support/inquiries/INQ-DEMO-002/replies",
            {"text": "Test", "idempotency_key": "test"},
        ),
    ],
)
def test_api_key_required_and_wrong_key_forbidden(client, method, path, body):
    for headers, status, code in [
        ({}, 401, "UNAUTHORIZED"),
        ({"X-API-Key": "wrong"}, 403, "FORBIDDEN"),
    ]:
        response = client.request(method, path, json=body, headers=headers)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert response.json()["error"]["request_id"]
    assert (
        client.request(
            method, path, json=body, headers={"X-API-Key": "test-key"}
        ).status_code
        == 200
    )


def test_health_docs_and_unauthorized_requests_do_not_consume_fault_budget(client):
    headers = {"X-API-Key": "test-key"}
    client.put(
        "/api/admin/scenarios/logistics/TRK-DEMO-002-1",
        json={"mode": "TIMEOUT_ONCE"},
        headers=headers,
    )
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/api/logistics/shipments/TRK-DEMO-002-1").status_code == 401
    assert (
        client.get(
            "/api/logistics/shipments/TRK-DEMO-002-1", headers=headers
        ).status_code
        == 504
    )
    assert (
        client.get(
            "/api/logistics/shipments/TRK-DEMO-002-1", headers=headers
        ).status_code
        == 200
    )
    spec = client.get("/openapi.json").json()
    assert spec["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"


def test_internal_errors_are_structured_without_leaking_data(tmp_path, monkeypatch):
    app = create_app(str(tmp_path / "errors.sqlite3"), api_key="test-key")
    with TestClient(app, raise_server_exceptions=False) as client:

        def broken(*args):
            raise RuntimeError("sensitive source content")

        monkeypatch.setattr(app.state.store, "get", broken)
        response = client.get(
            "/api/oms/orders/ORD-DEMO-002",
            headers={
                "X-API-Key": "test-key",
                "X-Request-Id": "internal-test",
            },
        )
        assert response.status_code == 500
        assert response.json() == {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Sandbox internal error",
                "request_id": "internal-test",
            }
        }
        assert response.headers["X-Request-Id"] == "internal-test"
        assert "sensitive" not in response.text


def test_new_customer_ingress_is_authenticated_and_rejection_is_side_effect_free(
    client,
):
    command = {"customer_message": "New question", "idempotency_key": "auth-ingress"}
    assert client.post("/api/support/inquiries", json=command).status_code == 401
    assert (
        client.post(
            "/api/support/inquiries", json=command, headers={"X-API-Key": "wrong"}
        ).status_code
        == 403
    )
    accepted = client.post(
        "/api/support/inquiries", json=command, headers={"X-API-Key": "test-key"}
    )
    assert accepted.status_code == 201
    path = f"/api/support/inquiries/{accepted.json()['inquiry_id']}/messages"
    assert (
        client.post(
            path, json={"text": "Follow-up", "idempotency_key": "k"}
        ).status_code
        == 401
    )
    messages = client.get(path, headers={"X-API-Key": "test-key"})
    assert len(messages.json()) == 1


def test_default_service_key_is_active(tmp_path, monkeypatch):
    monkeypatch.delenv("SANDBOX_API_KEY")
    with TestClient(create_app(str(tmp_path / "default.sqlite3"))) as client:
        assert client.get("/api/support/inquiries").status_code == 401
        assert (
            client.get(
                "/api/support/inquiries", headers={"X-API-Key": "demo-commerce-key"}
            ).status_code
            == 200
        )
