from __future__ import annotations

from app.tools.railway import ALLOWED_TOOLS, execute_tool


def test_search_tool_returns_data_and_notes(provider):
    result = execute_tool(
        "search_trains",
        {"from_station": "ALPJ", "to_station": "BETN", "journey_date": "2026-11-15"},
        provider,
    )
    assert result.ok
    assert result.data["count"] == 3
    assert result.data["trains"][0]["train_number"] == "00001"
    assert any("Scheduled timetable" in note for note in result.notes)
    assert result.provenance is not None


def test_tool_accepts_json_string_arguments(provider):
    result = execute_tool(
        "get_train_schedule", '{"train_number": "00001"}', provider
    )
    assert result.ok
    assert len(result.data["stops"]) == 3


def test_missing_required_argument(provider):
    result = execute_tool("search_trains", {"from_station": "ALPJ"}, provider)
    assert not result.ok
    assert result.error.code == "invalid_arguments"


def test_extra_arguments_are_rejected(provider):
    result = execute_tool(
        "get_train_schedule", {"train_number": "00001", "sql": "DROP TABLE trains"}, provider
    )
    assert not result.ok
    assert result.error.code == "invalid_arguments"


def test_unknown_tool_is_rejected(provider):
    result = execute_tool("run_shell", {"command": "ls"}, provider)
    assert not result.ok
    assert result.error.code == "unknown_tool"
    assert "run_shell" in result.error.message


def test_invalid_date(provider):
    result = execute_tool(
        "search_trains",
        {"from_station": "ALPJ", "to_station": "BETN", "journey_date": "31-02-2026"},
        provider,
    )
    assert not result.ok
    assert result.error.code == "invalid_arguments"


def test_invalid_train_number(provider):
    result = execute_tool("get_train_schedule", {"train_number": "abcd"}, provider)
    assert not result.ok
    assert result.error.code == "invalid_arguments"


def test_unknown_train(provider):
    result = execute_tool("get_train_schedule", {"train_number": "99999"}, provider)
    assert not result.ok
    assert result.error.code == "train_not_found"


def test_ambiguous_station_error(provider):
    result = execute_tool(
        "search_trains",
        {"from_station": "Nagar", "to_station": "BETN", "journey_date": "2026-11-15"},
        provider,
    )
    assert not result.ok
    assert result.error.code == "ambiguous_station"
    assert result.error.details["candidates"]


def test_live_status_is_typed_unsupported(provider):
    result = execute_tool("get_live_status", {"train_number": "00001"}, provider)
    assert not result.ok
    assert result.error.code == "feature_unsupported"
    assert result.error.details["feature"] == "live_status"


def test_fare_is_typed_unsupported(provider):
    result = execute_tool(
        "get_fare_and_availability",
        {
            "train_number": "00001",
            "from_station": "ALPJ",
            "to_station": "BETN",
            "journey_date": "2026-11-15",
            "travel_class": "SL",
        },
        provider,
    )
    assert not result.ok
    assert result.error.code == "feature_unsupported"


def test_compare_tool(provider):
    result = execute_tool(
        "compare_trains",
        {
            "train_numbers": ["00001", "00002"],
            "from_station": "ALPJ",
            "to_station": "BETN",
            "journey_date": "2026-11-15",
        },
        provider,
    )
    assert result.ok
    assert result.data["count"] == 2
    assert result.data["trains"][0]["train_number"] == "00001"


def test_compare_duplicate_numbers_rejected(provider):
    result = execute_tool(
        "compare_trains",
        {
            "train_numbers": ["00001", "00001"],
            "from_station": "ALPJ",
            "to_station": "BETN",
            "journey_date": "2026-11-15",
        },
        provider,
    )
    assert not result.ok
    assert result.error.code == "invalid_arguments"


def test_tool_allowlist_is_closed():
    assert ALLOWED_TOOLS == frozenset(
        {
            "search_trains",
            "get_train_schedule",
            "get_train_route",
            "compare_trains",
            "get_live_status",
            "get_fare_and_availability",
        }
    )


def test_provider_failure_is_safe(tmp_path):
    from app.providers.local import LocalTimetableProvider

    result = execute_tool(
        "get_train_schedule", {"train_number": "00001"}, LocalTimetableProvider(tmp_path / "no.db")
    )
    assert not result.ok
    assert result.error.code == "dataset_unavailable"
    assert "Traceback" not in result.error.message
