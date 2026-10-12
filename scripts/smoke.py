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


def main():
    parser = argparse.ArgumentParser(description="Real HTTP Sandbox smoke test")
    parser.add_argument("--base-time", help="Explicit UTC reset reference time")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "SANDBOX_DB_PATH": str(Path(directory) / "smoke.sqlite3")}
        if args.base_time:
            subprocess.run(
                [sys.executable, "-m", "app.reset", "--base-time", args.base_time],
                env=env,
                check=True,
                timeout=15,
            )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Uvicorn exited before startup")
                    try:
                        response = client.get("/health")
                        if response.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Startup timed out")
                assert response.json()["database"] == "ok"
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
                inquiry = client.get("/api/support/inquiries/INQ-DEMO-004").json()
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
                else:
                    raise AssertionError("Slow response did not trigger client timeout")
                assert client.get("/health").status_code == 200
                assert client.delete(control).status_code == 204
                assert client.get(first).status_code == 200
                print("Core workflow: reads, fault recovery and reply retry passed")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
