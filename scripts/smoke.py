"""Exercise representative scenarios over real HTTP against a child process."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def main():
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "SANDBOX_DB_PATH": str(Path(directory) / "smoke.sqlite3")}
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
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
