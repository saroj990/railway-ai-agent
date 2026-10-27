from __future__ import annotations

from app.router_utils import extract_route, parse_date


def test_parse_iso_date():
    assert parse_date("trains on 2026-11-15") == "2026-11-15"


def test_parse_day_month_name():
    assert parse_date("15 November 2026") == "2026-11-15"
    assert parse_date("on 15 Nov 2026") == "2026-11-15"


def test_parse_indian_numeric_date():
    assert parse_date("15-11-2026") == "2026-11-15"
    assert parse_date("15/11/2026") == "2026-11-15"


def test_invalid_date_returns_none():
    assert parse_date("31-02-2026") is None
    assert parse_date("sometime next week") is None


def test_extract_route_from_sentence():
    assert extract_route("Trains from Bhubaneswar to New Delhi on 15 November 2026") == (
        "Bhubaneswar",
        "New Delhi",
    )


def test_extract_route_between():
    assert extract_route("trains between Bhubaneswar and New Delhi on 2026-11-15") == (
        "Bhubaneswar",
        "New Delhi",
    )


def test_extract_route_returns_none_for_no_route():
    assert extract_route("Show me train 12801") is None
