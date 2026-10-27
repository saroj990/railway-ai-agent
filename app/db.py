from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS stations (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trains (
    number TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS train_stops (
    train_number TEXT NOT NULL,
    station_code TEXT NOT NULL,
    seq INTEGER NOT NULL,
    arrival TEXT,
    departure TEXT,
    distance_km REAL,
    PRIMARY KEY (train_number, seq),
    FOREIGN KEY (train_number) REFERENCES trains(number),
    FOREIGN KEY (station_code) REFERENCES stations(code)
);

CREATE INDEX IF NOT EXISTS idx_stops_station ON train_stops(station_code);
CREATE INDEX IF NOT EXISTS idx_stops_train ON train_stops(train_number);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path | str, read_only: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(path: Path | str, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    conn = connect(path, read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def init_db(path: Path | str) -> None:
    with session(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}


def set_meta(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    conn.executemany(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        list(values.items()),
    )
