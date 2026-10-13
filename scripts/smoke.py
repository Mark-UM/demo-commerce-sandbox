"""Exercise representative scenarios over real HTTP against a child process."""

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx


def wait_ready(client, process):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Uvicorn exited before startup")
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return response
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    raise RuntimeError("Startup timed out")


def main():
    parser = argparse.ArgumentParser(description="Real HTTP Sandbox smoke test")
    parser.add_argument("--base-time", help="Explicit UTC reset reference time")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "SANDBOX_DB_PATH": str(Path(directory) / "smoke.sqlite3")}
        env["SANDBOX_API_KEY"] = "smoke-test-key"
        if args.base_time:
            subprocess.run(
                [sys.executable, "-m", "app.reset", "--base-time", args.base_time],
                env=env,
                check=True,
                timeout=15,
            )
        server_command = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        process = subprocess.Popen(server_command, env=env)
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                timeout=2,
                headers={"X-API-Key": "smoke-test-key"},
            ) as client:
                response = wait_ready(client, process)
                assert response.json()["database"] == "ok"
                console = client.get("/")
                assert console.status_code == 200
                assert "DemoCommerce" in console.text
                assert client.get("/static/console.js").status_code == 200
                assert client.get("/static/console.css").status_code == 200
                assert client.get("/api/policy/order-support").status_code == 200
                summary = client.get("/api/admin/summary")
                assert summary.status_code == 200
                assert summary.json()["orders"] == 120
                assert summary.json()["inquiries"] == 60
                assert (
                    client.get("/api/oms/customers/CUS-DEMO-001/orders").status_code
                    == 200
                )
                if args.base_time:
                    reference = datetime.fromisoformat(args.base_time)
                    for number, age in [
                        (2, timedelta(minutes=10)),
                        (7, timedelta(hours=72)),
                    ]:
                        shipment = client.get(
                            f"/api/logistics/shipments/TRK-DEMO-{number:03}-1"
                        )
                        assert shipment.status_code == 200
                        assert (
                            datetime.fromisoformat(shipment.json()["updated_at"])
                            == reference - age
                        )
                for scenario, path, status in [
                    ("S02", "/api/logistics/shipments/TRK-DEMO-002-1", 200),
                    ("S04", "/api/oms/orders/ORD-DEMO-004/parcels", 200),
                    ("S06", "/api/warehouse/orders/ORD-DEMO-006/notes", 200),
                    ("S06", "/api/logistics/shipments/TRK-DEMO-006-1", 200),
                    ("S08", "/api/logistics/shipments/TRK-DEMO-008-1", 504),
                    ("S08", "/api/oms/orders/ORD-DEMO-008", 200),
                    ("S09", "/api/warehouse/orders/ORD-DEMO-009/notes", 503),
                    ("S09", "/api/logistics/shipments/TRK-DEMO-009-1", 200),
                    ("S12", "/api/oms/orders/ORD-DEMO-012", 404),
                ]:
                    result = client.get(path)
                    assert result.status_code == status, result.text
                    print(scenario, result.status_code, result.json())
                # A real source workflow: inquiry -> order -> parcels -> independent
                # reads -> externally supplied reply -> idempotent retry.
                inquiry_list = client.get(
                    "/api/support/inquiries", params={"order_id": "ORD-DEMO-004"}
                )
                assert inquiry_list.status_code == 200
                assert len(inquiry_list.json()) == 1
                inquiry = inquiry_list.json()[0]
                assert (
                    client.get(f"/api/support/inquiries/{inquiry['inquiry_id']}").json()
                    == inquiry
                )
                order_id = inquiry["order_id"]
                assert client.get(f"/api/oms/orders/{order_id}").status_code == 200
                parcels = client.get(f"/api/oms/orders/{order_id}/parcels").json()
                control = (
                    "/api/admin/scenarios/logistics/" + parcels[0]["tracking_number"]
                )
                first = "/api/logistics/shipments/" + parcels[0]["tracking_number"]
                assert (
                    client.put(control, json={"mode": "TIMEOUT_ONCE"}).status_code
                    == 200
                )
                assert client.get(first).status_code == 504
                assert client.get(first).status_code == 200
                assert client.get(first + "/events").status_code == 200
                assert (
                    client.get(
                        "/api/logistics/shipments/" + parcels[1]["tracking_number"]
                    ).status_code
                    == 200
                )
                assert (
                    client.get(f"/api/warehouse/orders/{order_id}/notes").status_code
                    == 200
                )
                reply_path = "/api/support/inquiries/INQ-DEMO-004/replies"
                command = {"text": "Smoke-test reply.", "idempotency_key": "smoke-1"}
                receipt = client.post(reply_path, json=command)
                assert receipt.status_code == 200
                assert client.post(reply_path, json=command).json() == receipt.json()
                pending = client.get(
                    "/api/support/inquiries",
                    params={
                        "order_id": order_id,
                        "status": "OPEN",
                    },
                )
                assert pending.status_code == 200
                assert pending.json() == []
                replied = client.get(
                    "/api/support/inquiries",
                    params={
                        "order_id": order_id,
                        "status": "REPLIED",
                    },
                )
                assert replied.status_code == 200
                assert replied.json() == [
                    {
                        **inquiry,
                        "status": "REPLIED",
                        "updated_at": receipt.json()["sent_at"],
                    }
                ]
                history = client.get(reply_path)
                assert history.status_code == 200
                assert history.json() == [
                    {**receipt.json(), **command, "inquiry_id": inquiry["inquiry_id"]}
                ]
                assert (
                    client.put(
                        control, json={"mode": "SLOW_RESPONSE", "delay_ms": 500}
                    ).status_code
                    == 200
                )
                try:
                    client.get(first, timeout=0.05)
                except httpx.ReadTimeout:
                    print("Core workflow: real client read timeout confirmed")
                    # The client timed out, but the delayed server request still
                    # finishes. Drain it before starting a new run with reset.
                    time.sleep(0.5)
                else:
                    raise AssertionError("Slow response did not trigger client timeout")
                assert client.get("/health").status_code == 200
                assert client.delete(control).status_code == 204
                assert client.get(first).status_code == 200
                print("Core workflow: reads, fault recovery and reply retry passed")
                # Reset the running environment entirely over HTTP.
                golden_control = "/api/admin/scenarios/logistics/TRK-DEMO-008-1"
                assert (
                    client.put(golden_control, json={"mode": "NORMAL"}).status_code
                    == 200
                )
                reset_body = {"base_time": args.base_time} if args.base_time else {}
                restored = client.post("/api/admin/reset", json=reset_body)
                assert restored.status_code == 200
                assert restored.json()["status"] == "RESET"
                assert client.get("/api/admin/scenarios").json() == []
                assert client.get(reply_path).json() == []
                assert (
                    client.get("/api/logistics/shipments/TRK-DEMO-008-1").status_code
                    == 504
                )
                assert (
                    client.get("/api/warehouse/orders/ORD-DEMO-009/notes").status_code
                    == 503
                )
                assert client.get(first).status_code == 200
                after_reset = client.post(reply_path, json=command)
                assert after_reset.status_code == 200
                assert after_reset.json()["reply_id"] != receipt.json()["reply_id"]
                assert (
                    client.post(reply_path, json=command).json() == after_reset.json()
                )
                print("Reset workflow: defaults restored and new reply run verified")
                verifier = [
                    sys.executable,
                    "scripts/verify_running.py",
                    "--base-url",
                    f"http://127.0.0.1:{port}",
                    "--receipt-file",
                    str(Path(directory) / "receipt.json"),
                ]
                subprocess.run([*verifier, "--reset"], env=env, check=True, timeout=30)
                process.terminate()
                process.wait(timeout=10)
                process = subprocess.Popen(server_command, env=env)
                wait_ready(client, process)
                subprocess.run(verifier, env=env, check=True, timeout=30)
                subprocess.run(
                    [
                        sys.executable,
                        "scripts/live_conversation.py",
                        "--base-url",
                        f"http://127.0.0.1:{port}",
                    ],
                    env=env,
                    check=True,
                    timeout=30,
                )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
