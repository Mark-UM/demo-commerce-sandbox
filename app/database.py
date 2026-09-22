import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.schemas import Receipt, ReplyCommand
from app.seed import records


class Store:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self, reset: bool = False):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS metadata (version TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS records (
                collection TEXT NOT NULL, lookup_key TEXT NOT NULL,
                payload TEXT NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS record_lookup
                ON records(collection, lookup_key)""")
            db.execute("""CREATE TABLE IF NOT EXISTS replies (
                inquiry_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                text TEXT NOT NULL, receipt TEXT NOT NULL,
                PRIMARY KEY (inquiry_id, idempotency_key))""")
            if reset:
                for table in ("records", "replies", "metadata"):
                    db.execute(f"DELETE FROM {table}")
            if not db.execute("SELECT version FROM metadata").fetchone():
                db.executemany(
                    "INSERT INTO records VALUES (?, ?, ?)",
                    [
                        (kind, key, value.model_dump_json())
                        for kind, key, value in records()
                    ],
                )
                db.execute("INSERT INTO metadata VALUES ('s0-s1-v1')")

    def get(self, collection: str, key: str):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM records WHERE collection=? AND lookup_key=? "
                "ORDER BY rowid",
                (collection, key),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def reply(self, inquiry_id: str, command: ReplyCommand):
        # Serialize the lookup and insert across threads/processes, not just requests.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT text, receipt FROM replies "
                "WHERE inquiry_id=? AND idempotency_key=?",
                (inquiry_id, command.idempotency_key),
            ).fetchone()
            if row:
                if row[0] != command.text:
                    raise ValueError("Idempotency key already used with different text")
                return json.loads(row[1])
            receipt = Receipt(
                reply_id=f"REP-{uuid4()}", status="SENT", sent_at=datetime.now(UTC)
            )
            db.execute(
                "INSERT INTO replies VALUES (?, ?, ?, ?)",
                (
                    inquiry_id,
                    command.idempotency_key,
                    command.text,
                    receipt.model_dump_json(),
                ),
            )
            return receipt
