from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import init_db, session, set_meta  # noqa: E402

REQUIRED_COLUMNS = (
    "Train No",
    "Train Name",
    "SEQ",
    "Station Code",
    "Station Name",
    "Arrival time",
    "Departure Time",
    "Distance",
)

DEFAULT_SOURCE = "Indian Railways train timetable (data.gov.in open data)"
DEFAULT_SOURCE_URL = "https://www.data.gov.in/catalog/indian-railways-train-time-table"
DEFAULT_LICENCE = "Government Open Data License - India (GODL)"
DEFAULT_NOTE = (
    "Scheduled timetable only. The dataset has no running-day, live-status, fare or "
    "availability information."
)


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _clean_time(raw: str | None) -> str | None:
    if not raw:
        return None
    parts = raw.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if hours == 24 and minutes == 0:
        return "00:00"
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        return None
    return f"{hours:02d}:{minutes:02d}"


def _clean_distance(raw: str | None) -> float | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


def _dataset_date_from_name(path: Path) -> str | None:
    match = re.search(r"_(\d{8})\.csv$", path.name, flags=re.I)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%d%m%Y").date().isoformat()


def import_csv(
    csv_path: Path,
    db_path: Path,
    *,
    source: str = DEFAULT_SOURCE,
    source_url: str = DEFAULT_SOURCE_URL,
    licence: str = DEFAULT_LICENCE,
    dataset_date: str | None = None,
    note: str = DEFAULT_NOTE,
) -> dict[str, int]:
    """Build a fresh SQLite timetable from a data.gov.in style CSV.

    The database is written to a temporary file and swapped in atomically, so a
    failed import never leaves a half-written timetable in place.
    """
    csv_path, db_path = Path(csv_path), Path(db_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    text = _decode(csv_path)
    reader = csv.DictReader(io.StringIO(text))
    missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

    train_names: dict[str, str] = {}
    train_stops: dict[str, dict[int, dict]] = defaultdict(dict)
    station_names: dict[str, Counter] = defaultdict(Counter)
    skipped = 0

    for row in reader:
        number = (row.get("Train No") or "").strip()
        seq_raw = (row.get("SEQ") or "").strip()
        code = (row.get("Station Code") or "").strip().upper()
        if not number or not seq_raw or not code:
            skipped += 1
            continue
        try:
            seq = int(seq_raw)
        except ValueError:
            skipped += 1
            continue
        train_names.setdefault(number, (row.get("Train Name") or "").strip() or f"Train {number}")
        name = (row.get("Station Name") or "").strip()
        if name:
            station_names[code][name] += 1
        train_stops[number][seq] = {
            "station_code": code,
            "arrival": _clean_time(row.get("Arrival time")),
            "departure": _clean_time(row.get("Departure Time")),
            "distance_km": _clean_distance(row.get("Distance")),
        }

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_name(db_path.name + ".import")
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(tmp_path) + suffix)
        if candidate.exists():
            candidate.unlink()

    init_db(tmp_path)
    station_rows = []
    for code, counter in station_names.items():
        station_rows.append((code, counter.most_common(1)[0][0]))
    train_rows = []
    stop_rows = []
    valid_trains = 0

    for number, stops_by_seq in train_stops.items():
        if len(stops_by_seq) < 2:
            skipped += len(stops_by_seq)
            continue
        valid_trains += 1
        train_rows.append((number, train_names[number]))
        sequences = sorted(stops_by_seq)
        last = sequences[-1]
        for index, seq in enumerate(sequences):
            stop = stops_by_seq[seq]
            arrival = None if index == 0 else stop["arrival"]
            departure = None if seq == last else stop["departure"]
            stop_rows.append(
                (
                    number,
                    stop["station_code"],
                    seq,
                    arrival,
                    departure,
                    stop["distance_km"],
                )
            )

    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {
        "source": source,
        "source_url": source_url,
        "licence": licence,
        "dataset_date": dataset_date or _dataset_date_from_name(csv_path) or "",
        "retrieved_at": retrieved_at,
        "csv_file": csv_path.name,
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "trains": str(valid_trains),
        "stations": str(len(station_rows)),
        "stops": str(len(stop_rows)),
        "note": note,
    }

    try:
        with session(tmp_path) as conn:
            conn.execute("BEGIN")
            conn.executemany(
                "INSERT INTO stations(code, name, aliases) VALUES(?, ?, '')", station_rows
            )
            conn.executemany("INSERT INTO trains(number, name) VALUES(?, ?)", train_rows)
            conn.executemany(
                "INSERT INTO train_stops(train_number, station_code, seq, arrival, departure, "
                "distance_km) VALUES(?, ?, ?, ?, ?, ?)",
                stop_rows,
            )
            set_meta(conn, meta)
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(tmp_path) + suffix)
            if candidate.exists():
                candidate.unlink()
        raise

    for suffix in ("-wal", "-shm"):
        stale = Path(str(db_path) + suffix)
        if stale.exists():
            stale.unlink()
    os.replace(tmp_path, db_path)

    return {
        "trains": valid_trains,
        "stations": len(station_rows),
        "stops": len(stop_rows),
        "skipped_rows": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import an Indian Railways timetable CSV into SQLite.")
    parser.add_argument("--csv", required=True, type=Path, help="Path to the timetable CSV export.")
    parser.add_argument("--db", type=Path, default=Path("data/railways.db"), help="Target SQLite file.")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="Human-readable source name.")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL, help="Source URL (recorded in metadata).")
    parser.add_argument("--licence", default=DEFAULT_LICENCE, help="Dataset licence.")
    parser.add_argument(
        "--dataset-date",
        default=None,
        help="Dataset publication date (YYYY-MM-DD). Defaults to the date in the filename.",
    )
    parser.add_argument("--note", default=DEFAULT_NOTE, help="Freshness/limitation note.")
    args = parser.parse_args()

    stats = import_csv(
        args.csv,
        args.db,
        source=args.source,
        source_url=args.source_url,
        licence=args.licence,
        dataset_date=args.dataset_date,
        note=args.note,
    )
    print(
        f"Imported {stats['trains']:,} trains, {stats['stations']:,} stations, "
        f"{stats['stops']:,} stops into {args.db}"
    )
    if stats["skipped_rows"]:
        print(f"Skipped {stats['skipped_rows']:,} malformed or single-stop rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
