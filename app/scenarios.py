from app.errors import SourceError

# A narrow fault boundary: future delay/rate-limit/malformed response behavior
# can be introduced here without changing source data or coupling routers.
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


def apply_failure(system: str, key: str):
    if failure := FAILURES.get((system, key)):
        raise SourceError(*failure)
