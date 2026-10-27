from __future__ import annotations

from typing import Any

from app.models import ToolResult


def fmt_duration(minutes: int | None) -> str:
    if minutes is None:
        return "Not available"
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins:02d}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "/")


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    return "\n".join(lines)


def _source_line(result: ToolResult) -> str:
    prov = result.provenance
    if prov is None:
        return ""
    bits = [f"Source: {prov.source}"]
    if prov.dataset_date:
        bits.append(f"dataset dated {prov.dataset_date}")
    if prov.retrieved_at:
        bits.append(f"imported {prov.retrieved_at[:10]}")
    return "\n\n_" + "; ".join(bits) + "._"


def render_search(result: ToolResult) -> str:
    if not result.ok or not isinstance(result.data, dict):
        return render_error(result)
    data = result.data
    trains = data.get("trains") or []
    if not trains:
        return "No direct trains were found between those stations in the imported timetable." + (
            _source_line(result)
        )
    origin = (data.get("from_station") or {}).get("name", "origin")
    destination = (data.get("to_station") or {}).get("name", "destination")
    rows = [
        [
            train.get("train_number"),
            train.get("train_name"),
            train.get("departure"),
            train.get("arrival"),
            fmt_duration(train.get("duration_minutes")),
            train.get("stops"),
            train.get("distance_km"),
        ]
        for train in trains
    ]
    table = md_table(
        ["Train", "Name", "Departs", "Arrives", "Duration", "Stops en route", "Km"], rows
    )
    return (
        f"**Trains from {origin} to {destination}**\n\n"
        + table
        + "\n\n"
        + " ".join(result.notes)
        + _source_line(result)
    )


def render_schedule(result: ToolResult) -> str:
    if not result.ok or not isinstance(result.data, dict):
        return render_error(result)
    data = result.data
    stops = data.get("stops") or []
    rows = [
        [
            stop.get("sequence"),
            f"{stop.get('station_name')} ({stop.get('station_code')})",
            stop.get("arrival"),
            stop.get("departure"),
            f"{stop.get('halt_minutes')}m" if stop.get("halt_minutes") is not None else "—",
            stop.get("day"),
            stop.get("distance_km"),
        ]
        for stop in stops
    ]
    table = md_table(["#", "Station", "Arrives", "Departs", "Halt", "Day", "Km"], rows)
    return (
        f"**Train {data.get('train_number')} — {data.get('train_name')}**\n\n"
        + table
        + "\n\n"
        + " ".join(result.notes)
        + _source_line(result)
    )


def render_comparison(result: ToolResult) -> str:
    if not result.ok or not isinstance(result.data, dict):
        return render_error(result)
    trains = result.data.get("trains") or []
    rows = [
        [
            train.get("train_number"),
            train.get("train_name"),
            train.get("departure"),
            train.get("arrival"),
            fmt_duration(train.get("duration_minutes")),
            train.get("stops"),
            train.get("distance_km"),
        ]
        for train in trains
    ]
    table = md_table(
        ["Train", "Name", "Departs", "Arrives", "Duration", "Stops en route", "Km"], rows
    )
    fastest = trains[0] if trains else None
    footer = ""
    if fastest:
        footer = (
            f"\n\nFastest: **{fastest.get('train_number')} {fastest.get('train_name')}** "
            f"({fmt_duration(fastest.get('duration_minutes'))})."
        )
    return table + footer + "\n\n" + " ".join(result.notes) + _source_line(result)


def render_error(result: ToolResult) -> str:
    error = result.error
    if error is None:
        return "The railway data source returned no usable data."
    details = error.details or {}
    hint = details.get("hint")
    candidates = details.get("candidates")
    text = error.message
    if candidates:
        options = ", ".join(f"{c['code']} ({c['name']})" for c in candidates)
        text += f" Options: {options}."
    if hint:
        text += f" {hint}"
    return text


def render_tool_result(result: ToolResult) -> str:
    if not result.ok:
        return render_error(result)
    if result.tool == "search_trains":
        return render_search(result)
    if result.tool in ("get_train_schedule", "get_train_route"):
        return render_schedule(result)
    if result.tool == "compare_trains":
        return render_comparison(result)
    return "No renderer for this result."
