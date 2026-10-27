from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import get_meta, session
from app.models import (
    ComparisonRow,
    Provenance,
    Station,
    TrainSchedule,
    TrainStop,
    TrainSummary,
)
from app.providers.base import (
    AmbiguousStation,
    DatasetUnavailable,
    FeatureUnsupported,
    RailwayProvider,
    StationNotFound,
    TrainNotFound,
)

MAX_SEARCH_RESULTS = 50

_CODE_IN_PARENS = re.compile(r"\(([A-Za-z]{2,6})\)\s*$")
_PUNCT = re.compile(r"[^A-Z0-9 ]+")
_SPACES = re.compile(r"\s+")
_SUFFIXES = (" JN", " JUNCTION", " JN.")


def _norm(value: str) -> str:
    value = value.upper().replace("&", " AND ")
    value = _PUNCT.sub(" ", value)
    return _SPACES.sub(" ", value).strip()


def _loose(value: str) -> str:
    base = _norm(value)
    for suffix in _SUFFIXES:
        if base.endswith(suffix.strip()):
            base = base[: -len(suffix.strip())].strip()
    return base


def _to_minutes(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.split(":")
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        return None
    return hours * 60 + minutes


def _fmt(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _halt_minutes(arrival: str | None, departure: str | None) -> int | None:
    start, end = _to_minutes(arrival), _to_minutes(departure)
    if start is None or end is None:
        return None
    return (end - start) % (24 * 60)


def _segment_duration(stops: list[sqlite3.Row], from_seq: int, to_seq: int) -> int | None:
    """Duration in minutes, rolling days forward as the schedule crosses midnight."""
    segment = [s for s in stops if from_seq <= s["seq"] <= to_seq]
    if len(segment) < 2:
        return None
    first_departure = _to_minutes(segment[0]["departure"])
    if first_departure is None:
        return None
    start = first_departure
    cursor = start
    for index, stop in enumerate(segment[1:], start=1):
        arrival = _to_minutes(stop["arrival"])
        if arrival is None:
            return None
        while arrival < cursor:
            arrival += 24 * 60
        cursor = arrival
        if index == len(segment) - 1:
            # The journey ends on arrival; a through train's onward departure is irrelevant.
            break
        departure = _to_minutes(stop["departure"])
        if departure is not None:
            while departure < cursor:
                departure += 24 * 60
            cursor = departure
    return cursor - start


def _annotate_days(stops: list[sqlite3.Row]) -> list[int]:
    """Assign a 1-based service day to every stop (data has no day column)."""
    days: list[int] = []
    cursor = 0
    day = 1
    for index, stop in enumerate(stops):
        if index == 0:
            departure = _to_minutes(stop["departure"])
            cursor = departure if departure is not None else 0
            days.append(1)
            continue

        arrival = _to_minutes(stop["arrival"])
        if arrival is None:
            days.append(day)
            continue

        absolute = arrival + (day - 1) * 24 * 60
        while absolute < cursor:
            absolute += 24 * 60
        cursor = absolute
        day = absolute // (24 * 60) + 1
        days.append(day)

        departure = _to_minutes(stop["departure"])
        if departure is not None:
            departure_abs = departure + (day - 1) * 24 * 60
            while departure_abs < cursor:
                departure_abs += 24 * 60
            cursor = departure_abs
            day = departure_abs // (24 * 60) + 1
    return days


class LocalTimetableProvider(RailwayProvider):
    """Read-only provider over a timetable SQLite file built by the importer."""

    name = "local_sqlite"

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    # -- lifecycle ---------------------------------------------------------
    def _require_db(self) -> None:
        if not self.db_path.exists():
            raise DatasetUnavailable(
                "The railway timetable database has not been imported yet.",
                details={
                    "hint": (
                        "Run `python -m scripts.import_timetable "
                        "--csv data/raw/Train_details_22122017.csv` first."
                    )
                },
            )

    def _conn(self) -> sqlite3.Connection:
        self._require_db()
        return session(self.db_path, read_only=True)

    def health(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {"status": "missing", "path": str(self.db_path), "trains": 0, "stations": 0}
        try:
            with self._conn() as conn:
                trains = conn.execute("SELECT COUNT(*) FROM trains").fetchone()[0]
                stations = conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
                meta = get_meta(conn)
            return {
                "status": "ok" if trains else "empty",
                "path": str(self.db_path),
                "trains": trains,
                "stations": stations,
                "source": meta.get("source"),
                "dataset_date": meta.get("dataset_date"),
                "retrieved_at": meta.get("retrieved_at"),
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {"status": "error", "path": str(self.db_path), "error": str(exc)}

    def provenance(self) -> Provenance:
        meta = {}
        if self.db_path.exists():
            with self._conn() as conn:
                meta = get_meta(conn)
        return Provenance(
            source=meta.get("source", "Imported Indian Railways timetable"),
            source_url=meta.get("source_url"),
            kind="scheduled",
            retrieved_at=meta.get("retrieved_at")
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            dataset_date=meta.get("dataset_date"),
            note=meta.get("note"),
        )

    # -- stations ----------------------------------------------------------
    def _all_stations(self) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute("SELECT code, name, aliases FROM stations").fetchall()

    def resolve_station(self, query: str) -> Station:
        raw = (query or "").strip()
        if len(raw) < 2:
            raise StationNotFound(
                "Station name or code is too short.",
                details={"query": raw, "hint": "Use a station code such as NDLS or a full name."},
            )

        code_match = _CODE_IN_PARENS.search(raw)
        if code_match:
            raw = code_match.group(1)

        rows = self._all_stations()
        query_norm, query_loose = _norm(raw), _loose(raw)

        tiers: list[list[sqlite3.Row]] = [[] for _ in range(5)]
        for row in rows:
            code = row["code"].upper()
            name_norm, name_loose = _norm(row["name"]), _loose(row["name"])
            aliases = [_norm(a) for a in (row["aliases"] or "").split("|") if a.strip()]
            if code == raw.upper():
                tiers[0].append(row)
            elif name_norm == query_norm:
                tiers[1].append(row)
            elif name_loose == query_loose:
                tiers[2].append(row)
            elif query_norm in aliases:
                tiers[3].append(row)
            elif name_loose.startswith(query_loose + " ") or name_loose == query_loose:
                tiers[4].append(row)
            elif len(query_loose) >= 4 and query_loose in name_loose:
                tiers[4].append(row)

        for tier in tiers:
            if not tier:
                continue
            unique = {row["code"]: row for row in tier}
            if len(unique) == 1:
                row = next(iter(unique.values()))
                return Station(
                    code=row["code"],
                    name=row["name"].title(),
                    aliases=[a for a in (row["aliases"] or "").split("|") if a],
                )
            candidates = [
                {"code": r["code"], "name": r["name"].title()}
                for r in sorted(unique.values(), key=lambda r: r["code"])[:8]
            ]
            raise AmbiguousStation(
                f"'{raw}' matches more than one station. Which one did you mean?",
                details={"query": raw, "candidates": candidates},
            )

        raise StationNotFound(
            f"No station found for '{raw}'.",
            details={
                "query": raw,
                "hint": "Try the official station code (e.g. NDLS) or a fuller station name.",
            },
        )

    # -- trains ------------------------------------------------------------
    def search_trains(
        self, from_station: str, to_station: str, journey_date: str
    ) -> list[TrainSummary]:
        origin = self.resolve_station(from_station)
        destination = self.resolve_station(to_station)
        if origin.code == destination.code:
            raise StationNotFound("Origin and destination stations are the same.")

        with self._conn() as conn:
            matches = conn.execute(
                """
                SELECT a.train_number, t.name AS train_name,
                       a.seq AS from_seq, b.seq AS to_seq,
                       a.departure AS departure, b.arrival AS arrival,
                       a.distance_km AS from_km, b.distance_km AS to_km
                FROM train_stops a
                JOIN train_stops b
                  ON b.train_number = a.train_number
                 AND b.station_code = ?
                 AND b.seq > a.seq
                JOIN trains t ON t.number = a.train_number
                WHERE a.station_code = ?
                ORDER BY a.departure, a.train_number
                """,
                (destination.code, origin.code),
            ).fetchall()

            if not matches:
                return []

            numbers = [m["train_number"] for m in matches]
            placeholders = ",".join("?" * len(numbers))
            stop_rows = conn.execute(
                f"SELECT * FROM train_stops WHERE train_number IN ({placeholders}) "
                "ORDER BY train_number, seq",
                numbers,
            ).fetchall()

        by_train: dict[str, list[sqlite3.Row]] = {}
        for row in stop_rows:
            by_train.setdefault(row["train_number"], []).append(row)

        results: list[TrainSummary] = []
        for match in matches[:MAX_SEARCH_RESULTS]:
            stops = by_train.get(match["train_number"], [])
            duration = _segment_duration(stops, match["from_seq"], match["to_seq"])
            distance = None
            if match["from_km"] is not None and match["to_km"] is not None:
                distance = round(match["to_km"] - match["from_km"], 1)
            results.append(
                TrainSummary(
                    train_number=match["train_number"],
                    train_name=match["train_name"],
                    from_station=origin,
                    to_station=destination,
                    departure=_fmt(_to_minutes(match["departure"]))
                    if _to_minutes(match["departure"]) is not None
                    else None,
                    arrival=_fmt(_to_minutes(match["arrival"]))
                    if _to_minutes(match["arrival"]) is not None
                    else None,
                    duration_minutes=duration,
                    distance_km=distance,
                    stops=max(0, match["to_seq"] - match["from_seq"] - 1),
                    running_days=None,
                )
            )
        return results

    def get_train_schedule(self, train_number: str) -> TrainSchedule:
        with self._conn() as conn:
            train = conn.execute(
                "SELECT number, name FROM trains WHERE number = ?", (train_number,)
            ).fetchone()
            if train is None:
                raise TrainNotFound(
                    f"Train {train_number} is not in the imported timetable.",
                    details={"train_number": train_number},
                )
            rows = conn.execute(
                """
                SELECT s.seq, s.station_code, st.name AS station_name,
                       s.arrival, s.departure, s.distance_km
                FROM train_stops s
                JOIN stations st ON st.code = s.station_code
                WHERE s.train_number = ?
                ORDER BY s.seq
                """,
                (train_number,),
            ).fetchall()

        if not rows:
            raise TrainNotFound(
                f"Train {train_number} has no stops in the imported timetable.",
                details={"train_number": train_number},
            )

        days = _annotate_days(rows)
        stops: list[TrainStop] = []
        last_index = len(rows) - 1
        for index, (row, day) in enumerate(zip(rows, days)):
            arrival_minutes = _to_minutes(row["arrival"])
            departure_minutes = _to_minutes(row["departure"])
            stops.append(
                TrainStop(
                    sequence=row["seq"],
                    station_code=row["station_code"],
                    station_name=row["station_name"].title(),
                    arrival=None if index == 0 or arrival_minutes is None else _fmt(arrival_minutes),
                    departure=None
                    if index == last_index or departure_minutes is None
                    else _fmt(departure_minutes),
                    halt_minutes=None
                    if index in (0, last_index)
                    else _halt_minutes(row["arrival"], row["departure"]),
                    distance_km=round(row["distance_km"], 1)
                    if row["distance_km"] is not None
                    else None,
                    day=day,
                )
            )

        return TrainSchedule(
            train_number=train["number"],
            train_name=train["name"],
            stops=stops,
            running_days=None,
        )

    def get_train_route(self, train_number: str) -> TrainSchedule:
        return self.get_train_schedule(train_number)

    def compare_trains(
        self,
        train_numbers: list[str],
        from_station: str | None,
        to_station: str | None,
        journey_date: str | None,
    ) -> list[ComparisonRow]:
        if not from_station or not to_station:
            raise StationNotFound(
                "Comparing trains needs both a from-station and a to-station.",
                details={"hint": "Ask for the comparison on a specific route."},
            )
        origin = self.resolve_station(from_station)
        destination = self.resolve_station(to_station)

        with self._conn() as conn:
            placeholders = ",".join("?" * len(train_numbers))
            rows = conn.execute(
                f"""
                SELECT a.train_number, t.name AS train_name,
                       a.seq AS from_seq, b.seq AS to_seq,
                       a.departure AS departure, b.arrival AS arrival,
                       a.distance_km AS from_km, b.distance_km AS to_km
                FROM train_stops a
                JOIN train_stops b
                  ON b.train_number = a.train_number
                 AND b.station_code = ?
                 AND b.seq > a.seq
                JOIN trains t ON t.number = a.train_number
                WHERE a.station_code = ? AND a.train_number IN ({placeholders})
                """,
                [destination.code, origin.code, *train_numbers],
            ).fetchall()

            found = {row["train_number"] for row in rows}
            missing = [n for n in train_numbers if n not in found]
            if missing:
                raise TrainNotFound(
                    "Some trains do not serve that route in the imported timetable.",
                    details={"train_numbers": missing, "route": f"{origin.code}-{destination.code}"},
                )

            stop_rows = conn.execute(
                f"SELECT * FROM train_stops WHERE train_number IN ({placeholders}) "
                "ORDER BY train_number, seq",
                train_numbers,
            ).fetchall()

        by_train: dict[str, list[sqlite3.Row]] = {}
        for row in stop_rows:
            by_train.setdefault(row["train_number"], []).append(row)

        comparisons: list[ComparisonRow] = []
        for row in rows:
            stops = by_train.get(row["train_number"], [])
            distance = None
            if row["from_km"] is not None and row["to_km"] is not None:
                distance = round(row["to_km"] - row["from_km"], 1)
            departure = _to_minutes(row["departure"])
            arrival = _to_minutes(row["arrival"])
            comparisons.append(
                ComparisonRow(
                    train_number=row["train_number"],
                    train_name=row["train_name"],
                    departure=_fmt(departure) if departure is not None else None,
                    arrival=_fmt(arrival) if arrival is not None else None,
                    duration_minutes=_segment_duration(stops, row["from_seq"], row["to_seq"]),
                    stops=max(0, row["to_seq"] - row["from_seq"] - 1),
                    distance_km=distance,
                )
            )
        comparisons.sort(key=lambda c: (c.duration_minutes is None, c.duration_minutes or 0))
        return comparisons

    # -- optional capabilities --------------------------------------------
    def get_live_status(self, train_number: str, journey_date: str | None = None) -> None:
        raise FeatureUnsupported(
            "Live running status is not configured for this deployment.",
            details={
                "feature": "live_status",
                "hint": (
                    "Live status needs an authorised live-data provider. "
                    "The imported timetable only contains scheduled times."
                ),
            },
        )

    def get_fare_and_availability(self, **kwargs: Any) -> None:
        raise FeatureUnsupported(
            "Fares and seat availability are not configured for this deployment.",
            details={
                "feature": "fare_availability",
                "hint": "These require an authorised reservation-data provider (e.g. IRCTC partner access).",
            },
        )
