"""Run with python -m app.reset while the service is stopped."""

import argparse
import os
from datetime import datetime, timedelta

from app.database import Store
from app.seed import BASE_TIME


def utc_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError
        return parsed
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Use an ISO 8601 UTC timestamp, e.g. 2026-10-13T06:00:00Z"
        ) from error


def main():
    parser = argparse.ArgumentParser(description="Reset deterministic Sandbox data")
    parser.add_argument(
        "--base-time",
        type=utc_time,
        default=BASE_TIME,
        help="Explicit UTC seed reference time (default: 2026-09-20T06:00:00Z)",
    )
    args = parser.parse_args()
    path = os.getenv("SANDBOX_DB_PATH", "sandbox.sqlite3")
    Store(path).initialize(reset=True, base_time=args.base_time)
    reference = args.base_time.isoformat().replace("+00:00", "Z")
    print(f"Reset {path}: S01-S12 restored at T0={reference}; replies removed.")


if __name__ == "__main__":
    main()
