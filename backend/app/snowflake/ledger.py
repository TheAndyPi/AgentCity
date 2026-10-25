"""Separate durable receipts. A pending receipt is never automatically resubmitted.

This conservative at-most-once policy trades availability after a crash for no
ambiguous repeat model charge. No operation touches the simulation writer lock.
"""

import json
import sqlite3
from datetime import UTC, datetime

from app.infrastructure.errors import require


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS receipts (
          owner TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
          response TEXT, PRIMARY KEY(owner,key));
        CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY, calls INTEGER NOT NULL);
        """)
        self.db.commit()

    def lookup(self, owner, key, fingerprint):
        row = self.db.execute(
            "SELECT fingerprint,response FROM receipts WHERE owner=? AND key=?", (owner, key)
        ).fetchone()
        if not row:
            return None
        require(row[0] == fingerprint, "IDEMPOTENCY_CONFLICT", "Key already used with another body", 409)
        require(
            row[1] is not None,
            "SERVICE_UNAVAILABLE",
            "Comparison interrupted or in progress; this key will not repeat vendor charges",
            503,
        )
        return json.loads(row[1])

    def begin(self, owner, key, fingerprint):
        self.db.execute("INSERT INTO receipts VALUES (?,?,?,NULL)", (owner, key, fingerprint))
        self.db.commit()

    def finish(self, owner, key, response):
        self.db.execute(
            "UPDATE receipts SET response=? WHERE owner=? AND key=?",
            (json.dumps(response, allow_nan=False), owner, key),
        )
        self.db.commit()

    def reserve_model(self, limit):
        day = datetime.now(UTC).date().isoformat()
        count = self.db.execute("SELECT calls FROM budget WHERE day=?", (day,)).fetchone()
        if count and count[0] >= limit:
            return False
        self.db.execute(
            "INSERT INTO budget VALUES (?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1", (day,)
        )
        self.db.commit()
        return True

    def close(self):
        self.db.close()
