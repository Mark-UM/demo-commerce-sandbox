"""Run with python -m app.reset while the service is stopped."""

import os

from app.database import Store


def main():
    path = os.getenv("SANDBOX_DB_PATH", "sandbox.sqlite3")
    Store(path).initialize(reset=True)
    print(f"Reset {path}: S01-S12 restored; all accepted replies removed.")


if __name__ == "__main__":
    main()
