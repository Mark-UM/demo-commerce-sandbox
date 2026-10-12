import time

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
        return
    if failure := FAILURES.get((system, key)):
        raise SourceError(*failure)
