import logging
import time
from datetime import datetime, timedelta

from fastapi import Response

from app.database import Store
from app.errors import SourceError

# Golden defaults remain in effect unless a record has an explicit override.
FAILURES = {
    ("logistics", "TRK-DEMO-008-1"): (
        504,
        "LOGISTICS_TEMPORARILY_UNAVAILABLE",
        "Demo logistics upstream timed out",
    ),
    ("warehouse", "ORD-DEMO-009"): (
        503,
        "WAREHOUSE_TEMPORARILY_UNAVAILABLE",
        "Demo warehouse unavailable",
    ),
}


def apply_failure(database: Store, system: str, key: str):
    if override := database.take_fault(system, key):
        mode, delay = override
        logging.getLogger("uvicorn.error").info(
            "scenario system=%s record=%s mode=%s", system, key, mode
        )
        if mode == "SLOW_RESPONSE":
            # Routers are synchronous: delay occupies a worker, not the event loop.
            time.sleep(delay / 1000)
        elif mode in ("TIMEOUT_ONCE", "ALWAYS_TIMEOUT"):
            raise SourceError(
                504,
                f"{system.upper()}_TEMPORARILY_UNAVAILABLE",
                f"Demo {system} upstream timed out",
            )
        elif mode == "HTTP_500":
            raise SourceError(
                500, "SCENARIO_FORCED_FAILURE", f"Demo {system} internal failure"
            )
        elif mode == "HTTP_429":
            raise SourceError(
                429,
                "RATE_LIMITED",
                f"Demo {system} rate limit",
                headers={"Retry-After": "1"},
            )
        elif mode == "PARTIAL_FAILURE":
            raise SourceError(
                503, "SCENARIO_FORCED_FAILURE", f"Demo {system} record unavailable"
            )
        return mode
    if failure := FAILURES.get((system, key)):
        raise SourceError(*failure)


def source_payload(mode: str | None, data, system: str):
    """Alter only this source response, never canonical snapshots or other systems."""
    if mode == "MALFORMED_RESPONSE":
        return Response(content='{"incomplete":', media_type="application/json")
    if mode == "EMPTY_RESULT":
        if isinstance(data, list):
            return []
        return {**data, "status": None, "updated_at": None}
    rows = data if isinstance(data, list) else [data]
    if mode == "STALE_DATA":
        for row in rows:
            for field in ("updated_at", "created_at", "occurred_at"):
                if row.get(field) is not None:
                    row[field] = (
                        (datetime.fromisoformat(row[field]) - timedelta(hours=72))
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
    elif mode == "CONFLICTING_DATA":
        for row in rows:
            if system == "warehouse":
                row["text"] = "Parcel has not been handed to the carrier today."
            else:
                row["status"] = "PICKED_UP"
                if "description" in row:
                    row["description"] = "Collected by carrier."
    return data
