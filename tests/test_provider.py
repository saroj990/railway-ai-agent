from __future__ import annotations

import pytest

from app.providers.base import (
    AmbiguousStation,
    DatasetUnavailable,
    FeatureUnsupported,
    StationNotFound,
    TrainNotFound,
)
from app.providers.local import LocalTimetableProvider


def test_resolve_station_by_code(provider):
    station = provider.resolve_station("ALPJ")
    assert station.code == "ALPJ"
    assert station.name == "Alpha Jn"


def test_resolve_station_by_name_is_case_insensitive(provider):
    assert provider.resolve_station("alpha nagar").code == "ALPN"


def test_resolve_station_by_name_with_code_in_parentheses(provider):
    assert provider.resolve_station("Beta Nagar (BETN)").code == "BETN"


def test_ambiguous_station_lists_candidates(provider):
    with pytest.raises(AmbiguousStation) as excinfo:
        provider.resolve_station("Nagar")
    candidates = {c["code"] for c in excinfo.value.details["candidates"]}
    assert {"ALPN", "BETN"} <= candidates


def test_unknown_station(provider):
    with pytest.raises(StationNotFound):
        provider.resolve_station("ZZZZ")
    with pytest.raises(StationNotFound):
        provider.resolve_station("A")


def test_search_trains_returns_direct_trains(provider):
    trains = provider.search_trains("ALPJ", "BETN", "2026-11-15")
    numbers = [t.train_number for t in trains]
    assert numbers == ["00001", "00004", "00002"]
    by_number = {t.train_number: t for t in trains}
    assert by_number["00001"].duration_minutes == 510  # 06:00 -> 14:30
    assert by_number["00001"].distance_km == 410
    assert by_number["00002"].duration_minutes == 710  # 18:00 -> 05:50 next day
    assert by_number["00002"].stops == 1
    assert by_number["00004"].stops == 0
    assert by_number["00004"].duration_minutes == 250  # 07:50 -> 12:00


def test_search_requires_correct_direction(provider):
    # 00003 only runs GAMM -> BETN, never ALPJ -> BETN.
    assert "00003" not in [t.train_number for t in provider.search_trains("ALPJ", "BETN", "2026-11-15")]
    numbers = [t.train_number for t in provider.search_trains("GAMM", "BETN", "2026-11-15")]
    assert numbers == ["00003", "00001"]


def test_search_no_results(provider):
    assert provider.search_trains("ALPN", "GAMM", "2026-11-15") == []


def test_schedule_marks_next_day(provider):
    schedule = provider.get_train_schedule("00002")
    assert [stop.day for stop in schedule.stops] == [1, 1, 2]
    assert schedule.stops[0].arrival is None
    assert schedule.stops[-1].departure is None
    assert schedule.stops[-1].arrival == "05:50"


def test_schedule_unknown_train(provider):
    with pytest.raises(TrainNotFound):
        provider.get_train_schedule("99999")


def test_live_status_is_unsupported(provider):
    with pytest.raises(FeatureUnsupported):
        provider.get_live_status("00001")


def test_fare_is_unsupported(provider):
    with pytest.raises(FeatureUnsupported):
        provider.get_fare_and_availability(train_number="00001")


def test_search_duration_stops_at_arrival_of_intermediate_station(provider):
    # 00001 reaches GAMM at 10:00 and continues at 10:10; duration must not include the halt.
    trains = provider.search_trains("ALPJ", "GAMM", "2026-11-15")
    assert [t.train_number for t in trains] == ["00001"]
    assert trains[0].duration_minutes == 240
    assert trains[0].arrival == "10:00"


def test_compare_sorts_by_duration(provider):
    rows = provider.compare_trains(["00001", "00002", "00004"], "ALPJ", "BETN", "2026-11-15")
    assert [row.train_number for row in rows] == ["00004", "00001", "00002"]
    assert rows[0].duration_minutes == 250


def test_compare_train_not_on_route(provider):
    with pytest.raises(TrainNotFound):
        provider.compare_trains(["00003"], "ALPJ", "BETN", "2026-11-15")


def test_missing_database_is_reported(tmp_path):
    provider = LocalTimetableProvider(tmp_path / "missing.db")
    assert provider.health()["status"] == "missing"
    with pytest.raises(DatasetUnavailable):
        provider.search_trains("ALPJ", "BETN", "2026-11-15")


def test_provenance_is_scheduled(provider):
    provenance = provider.provenance()
    assert provenance.kind == "scheduled"
    assert provenance.dataset_date == "2026-01-01"
    assert "fixture" in provenance.source.lower()
