"""Durable narration cache and operation receipts, separate from the simulation journal.

Audio files are named by random opaque IDs held in SQLite, never by caller input.
An entry with an unexpired issued URL is never evicted, so every advertised URL
stays usable until its expiry unless the caller's access is revoked.
"""

import json
import os
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

AUDIO_ID = re.compile(r"[0-9a-f]{32}")
OPERATION_LIMIT = 10000


@dataclass(frozen=True)
class AudioEntry:
    audio_id: str
    owner: str
    content_key: str
    simulation_id: str
    size: int
    expires_at: float
    tokens_until: float


class Store:
    def __init__(self, directory: Path, config):
        self.config = config
        self.directory = directory
        self.audio = directory / "audio"
        self.audio.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.writing = set()
        self.db = sqlite3.connect(directory / "narration.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS audio (
          audio_id TEXT PRIMARY KEY, owner TEXT NOT NULL, content_key TEXT NOT NULL,
          simulation_id TEXT NOT NULL, size INTEGER NOT NULL, created_at REAL NOT NULL,
          expires_at REAL NOT NULL, tokens_until REAL NOT NULL, accessed_at REAL NOT NULL,
          UNIQUE(owner, content_key));
        CREATE TABLE IF NOT EXISTS operations (
          owner TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
          audio_id TEXT NOT NULL, response TEXT NOT NULL, expires_at REAL NOT NULL,
          PRIMARY KEY(owner, key));
        CREATE TABLE IF NOT EXISTS secret (id INTEGER PRIMARY KEY CHECK (id = 1), value BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
        """)
        self.db.execute("INSERT OR IGNORE INTO secret VALUES (1, ?)", (secrets.token_bytes(32),))
        self.db.commit()
        self.secret = self.db.execute("SELECT value FROM secret").fetchone()[0]

    def close(self):
        with self.lock:
            self.db.close()

    def path(self, audio_id):
        if not AUDIO_ID.fullmatch(audio_id):
            raise ValueError("invalid audio id")
        return self.audio / f"{audio_id}.mp3"

    def _entry(self, row):
        return AudioEntry(*row) if row else None

    _COLUMNS = "audio_id, owner, content_key, simulation_id, size, expires_at, tokens_until"

    def get(self, audio_id, now):
        with self.lock:
            row = self.db.execute(
                f"SELECT {self._COLUMNS} FROM audio WHERE audio_id=? AND expires_at>?", (audio_id, now)
            ).fetchone()
        return self._entry(row)

    def find(self, owner, content_key, now):
        with self.lock:
            row = self.db.execute(
                f"SELECT {self._COLUMNS} FROM audio WHERE owner=? AND content_key=? AND expires_at>?",
                (owner, content_key, now),
            ).fetchone()
        entry = self._entry(row)
        if entry and not self._intact(entry):
            self._remove([entry.audio_id])
            return None
        return entry

    def _intact(self, entry):
        try:
            return self.path(entry.audio_id).stat().st_size == entry.size
        except OSError:
            return False

    def read(self, entry, now):
        data = self.path(entry.audio_id).read_bytes()
        if len(data) != entry.size:
            raise OSError("cached audio changed size")
        with self.lock:
            self.db.execute("UPDATE audio SET accessed_at=? WHERE audio_id=?", (now, entry.audio_id))
            self.db.commit()
        return data

    def usage(self):
        with self.lock:
            count, total = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM audio").fetchone()
        return count, total

    def _remove(self, audio_ids):
        with self.lock:
            for audio_id in audio_ids:
                self.db.execute("DELETE FROM audio WHERE audio_id=?", (audio_id,))
            self.db.commit()
        for audio_id in audio_ids:
            self.path(audio_id).unlink(missing_ok=True)

    def sweep(self, now):
        """Drop expired, damaged and orphaned entries. Runs at startup and before inserts."""
        with self.lock:
            expired = [
                r[0] for r in self.db.execute("SELECT audio_id FROM audio WHERE expires_at<=?", (now,))
            ]
            self.db.execute("DELETE FROM operations WHERE expires_at<=?", (now,))
            self.db.commit()
            self._remove(expired)
            rows = self.db.execute(f"SELECT {self._COLUMNS} FROM audio").fetchall()
            damaged = [entry.audio_id for entry in map(self._entry, rows) if not self._intact(entry)]
            self._remove(damaged)
            known = {r[0] for r in self.db.execute("SELECT audio_id FROM audio")}
            for path in self.audio.iterdir():
                if path not in self.writing and (path.suffix != ".mp3" or path.stem not in known):
                    path.unlink(missing_ok=True)

    def make_room(self, now, size, reserved_bytes, reserved_entries):
        """Evict least-recently-used entries without live URLs. False if still full."""
        self.sweep(now)
        with self.lock:
            count, total = self.usage()
            candidates = self.db.execute(
                "SELECT audio_id, size FROM audio WHERE tokens_until<=? ORDER BY accessed_at, audio_id",
                (now,),
            ).fetchall()
            evict = []
            for audio_id, entry_size in candidates:
                if (
                    count + reserved_entries + 1 <= self.config.cache_max_entries
                    and total + reserved_bytes + size <= self.config.cache_max_bytes
                ):
                    break
                evict.append(audio_id)
                count, total = count - 1, total - entry_size
            fits = (
                count + reserved_entries + 1 <= self.config.cache_max_entries
                and total + reserved_bytes + size <= self.config.cache_max_bytes
            )
            if fits:
                self._remove(evict)
            return fits

    def insert(self, owner, content_key, simulation_id, data, now):
        audio_id = secrets.token_hex(16)
        path = self.path(audio_id)
        temp = path.with_suffix(".tmp")
        with self.lock:
            self.writing.update((temp, path))
        try:
            with temp.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            with self.lock:
                stale = [
                    r[0]
                    for r in self.db.execute(
                        "SELECT audio_id FROM audio WHERE owner=? AND content_key=?", (owner, content_key)
                    )
                ]
                self._remove(stale)
                self.db.execute(
                    "INSERT INTO audio VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        audio_id,
                        owner,
                        content_key,
                        simulation_id,
                        len(data),
                        now,
                        now + self.config.cache_ttl,
                        0,
                        now,
                    ),
                )
                self.db.commit()
        finally:
            with self.lock:
                self.writing.difference_update((temp, path))
        return self.get(audio_id, now)

    def issue(self, entry, until):
        """Protect an entry until an issued URL expires."""
        with self.lock:
            self.db.execute(
                "UPDATE audio SET tokens_until=MAX(tokens_until, ?), expires_at=MAX(expires_at, ?) "
                "WHERE audio_id=?",
                (until, until, entry.audio_id),
            )
            self.db.commit()

    def operation(self, owner, key):
        with self.lock:
            row = self.db.execute(
                "SELECT fingerprint, audio_id, response, expires_at FROM operations WHERE owner=? AND key=?",
                (owner, key),
            ).fetchone()
        return None if row is None else (row[0], row[1], json.loads(row[2]), row[3])

    def record(self, owner, key, fingerprint, audio_id, response, expires_at):
        with self.lock:
            self.db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,?)",
                (owner, key, fingerprint, audio_id, json.dumps(response, allow_nan=False), expires_at),
            )
            self.db.execute(
                "DELETE FROM operations WHERE rowid NOT IN "
                "(SELECT rowid FROM operations ORDER BY expires_at DESC LIMIT ?)",
                (OPERATION_LIMIT,),
            )
            self.db.commit()

    def count(self, name, amount=1):
        with self.lock:
            self.db.execute(
                "INSERT INTO counters VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value=value+?",
                (name, amount, amount),
            )
            self.db.commit()

    def counters(self):
        with self.lock:
            return dict(self.db.execute("SELECT name, value FROM counters"))
