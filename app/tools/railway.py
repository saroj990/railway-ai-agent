from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from pydantic import Field, ValidationError

from app.models import StrictModel, ToolError, ToolResult
from app.providers.base import FeatureUnsupported, RailwayDataError, RailwayProvider

logger = logging.getLogger(__name__)

TRAIN_NUMBER_RE = re.compile(r"^\d{4,5}$")


class SearchTrainsArgs(StrictModel):
    from_station: str = Field(min_length=2, max_length=80)
    to_station: str = Field(min_length=2, max_length=80)
    journey_date: str = Field(min_length=8, max_length=10)


class TrainNumberArgs(StrictModel):
    train_number: str = Field(min_length=4, max_length=5)


class CompareTrainsArgs(StrictModel):
    train_numbers: list[str] = Field(min_length=2, max_length=5)
    from_station: str = Field(min_length=2, max_length=80)
    to_station: str = Field(min_length=2, max_length=80)
    journey_date: str = Field(min_length=8, max_length=10)


class LiveStatusArgs(StrictModel):
    train_number: str = Field(min_length=4, max_length=5)
    journey_date: str | None = Field(default=None, max_length=10)


class FareAvailabilityArgs(StrictModel):
    train_number: str = Field(min_length=4, max_length=5)
    from_station: str = Field(min_length=2, max_length=80)
    to_station: str = Field(min_length=2, max_length=80)
    journey_date: str = Field(min_length=8, max_length=10)
    travel_class: str | None = Field(default=None, max_length=4)


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_trains",
            "description": (
                "Find trains that stop at both the origin and destination, with departure, "
                "arrival, duration and distance. Use for 'trains from X to Y' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_station": {
                        "type": "string",
                        "description": "Origin station code (preferred) or name, e.g. BBS or Bhubaneswar.",
                    },
                    "to_station": {
                        "type": "string",
                        "description": "Destination station code (preferred) or name, e.g. NDLS or New Delhi.",
                    },
                    "journey_date": {
                        "type": "string",
                        "description": "Journey date as YYYY-MM-DD. Required even when the user omits it: ask the user instead of guessing.",
                    },
                },
                "required": ["from_station", "to_station", "journey_date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_train_schedule",
            "description": (
                "Get the full stop-by-stop scheduled timetable for one train: sequence, station, "
                "arrival, departure, halt and distance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "train_number": {"type": "string", "description": "Train number, e.g. 12801."}
                },
                "required": ["train_number"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_train_route",
            "description": "Get the list of stations a train stops at, in order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "train_number": {"type": "string", "description": "Train number, e.g. 12801."}
                },
                "required": ["train_number"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_trains",
            "description": (
                "Compare 2-5 trains on the same route by departure, arrival, duration, number of "
                "intermediate stops and distance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "train_numbers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 5,
                    },
                    "from_station": {"type": "string"},
                    "to_station": {"type": "string"},
                    "journey_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["train_numbers", "from_station", "to_station", "journey_date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_live_status",
            "description": (
                "Get live running status. Only available if an authorised live-data provider is "
                "configured; otherwise it returns a typed unsupported error."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "train_number": {"type": "string"},
                    "journey_date": {"type": "string", "description": "YYYY-MM-DD, optional"},
                },
                "required": ["train_number"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fare_and_availability",
            "description": (
                "Get fare and seat availability. Only available with an authorised reservation-data "
                "provider; otherwise it returns a typed unsupported error."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "train_number": {"type": "string"},
                    "from_station": {"type": "string"},
                    "to_station": {"type": "string"},
                    "journey_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "travel_class": {"type": "string", "description": "e.g. SL, 3A, 2A"},
                },
                "required": ["train_number", "from_station", "to_station", "journey_date"],
                "additionalProperties": False,
            },
        },
    },
]

ARG_MODELS: dict[str, type[StrictModel]] = {
    "search_trains": SearchTrainsArgs,
    "get_train_schedule": TrainNumberArgs,
    "get_train_route": TrainNumberArgs,
    "compare_trains": CompareTrainsArgs,
    "get_live_status": LiveStatusArgs,
    "get_fare_and_availability": FareAvailabilityArgs,
}

ALLOWED_TOOLS = frozenset(ARG_MODELS)


def _parse_date(value: str) -> str:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Date must be a valid date in YYYY-MM-DD format.")


def _validate_train_number(value: str) -> str:
    value = value.strip()
    if not TRAIN_NUMBER_RE.match(value):
        raise ValueError("Train number must be 4 or 5 digits.")
    return value


def _scheduled_note(provider: RailwayProvider) -> str:
    provenance = provider.provenance()
    parts = ["Scheduled timetable data, not live running status."]
    if provenance.dataset_date:
        parts.append(f"Dataset dated {provenance.dataset_date}.")
    parts.append(
        "Running days are not present in this dataset, so results do not confirm the train "
        "operates on the requested date."
    )
    return " ".join(parts)


def _dump(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, list):
        return [_dump(item) for item in model]
    return model


def _error(tool: str, code: str, message: str, details: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(
        ok=False, tool=tool, error=ToolError(code=code, message=message, details=details)
    )


def execute_tool(name: str, raw_arguments: Any, provider: RailwayProvider) -> ToolResult:
    """Validate and run one allowlisted tool. Never raises for expected failures."""
    if name not in ALLOWED_TOOLS:
        logger.warning("Rejected unknown tool name: %s", name)
        return _error(name, "unknown_tool", f"Tool '{name}' is not available.")

    arguments = raw_arguments
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return _error(name, "invalid_arguments", "Tool arguments were not valid JSON.")
    if not isinstance(arguments, dict):
        return _error(name, "invalid_arguments", "Tool arguments must be a JSON object.")

    model = ARG_MODELS[name]
    try:
        parsed = model.model_validate(arguments)
    except ValidationError as exc:
        safe = [
            {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return _error(name, "invalid_arguments", "Tool arguments failed validation.", {"errors": safe})

    try:
        provenance = provider.provenance()
        if name == "search_trains":
            args = SearchTrainsArgs.model_validate(parsed.model_dump())
            journey_date = _parse_date(args.journey_date)
            trains = provider.search_trains(args.from_station, args.to_station, journey_date)
            notes = [_scheduled_note(provider)]
            if not trains:
                notes.append("No direct trains found between these stations in the imported timetable.")
            if len(trains) >= 50:
                notes.append("Showing the first 50 matches; narrow the query for more precise results.")
            return ToolResult(
                ok=True,
                tool=name,
                data={
                    "journey_date": journey_date,
                    "from_station": trains[0].from_station.model_dump() if trains else None,
                    "to_station": trains[0].to_station.model_dump() if trains else None,
                    "trains": _dump(trains),
                    "count": len(trains),
                },
                provenance=provenance,
                notes=notes,
            )

        if name in ("get_train_schedule", "get_train_route"):
            train_number = _validate_train_number(parsed.train_number)  # type: ignore[attr-defined]
            schedule = (
                provider.get_train_schedule(train_number)
                if name == "get_train_schedule"
                else provider.get_train_route(train_number)
            )
            return ToolResult(
                ok=True,
                tool=name,
                data=_dump(schedule),
                provenance=provenance,
                notes=[_scheduled_note(provider)],
            )

        if name == "compare_trains":
            args = CompareTrainsArgs.model_validate(parsed.model_dump())
            numbers = [_validate_train_number(n) for n in args.train_numbers]
            if len(set(numbers)) != len(numbers):
                return _error(name, "invalid_arguments", "Train numbers must be unique.")
            journey_date = _parse_date(args.journey_date)
            rows = provider.compare_trains(numbers, args.from_station, args.to_station, journey_date)
            return ToolResult(
                ok=True,
                tool=name,
                data={"journey_date": journey_date, "trains": _dump(rows), "count": len(rows)},
                provenance=provenance,
                notes=[_scheduled_note(provider)],
            )

        if name == "get_live_status":
            train_number = _validate_train_number(parsed.train_number)  # type: ignore[attr-defined]
            journey_date = None
            if parsed.journey_date:  # type: ignore[attr-defined]
                journey_date = _parse_date(parsed.journey_date)  # type: ignore[attr-defined]
            provider.get_live_status(train_number, journey_date)
            return _error(name, "feature_unsupported", "Live status is not configured.")

        if name == "get_fare_and_availability":
            args = FareAvailabilityArgs.model_validate(parsed.model_dump())
            provider.get_fare_and_availability(
                train_number=_validate_train_number(args.train_number),
                from_station=args.from_station,
                to_station=args.to_station,
                journey_date=_parse_date(args.journey_date),
                travel_class=args.travel_class,
            )
            return _error(name, "feature_unsupported", "Fare data is not configured.")

    except FeatureUnsupported as exc:
        return _error(name, exc.code, exc.message, exc.details)
    except RailwayDataError as exc:
        return _error(name, exc.code, exc.message, exc.details)
    except ValueError as exc:
        return _error(name, "invalid_arguments", str(exc))
    except Exception:  # noqa: BLE001 - never leak internals to the model/user
        logger.exception("Unexpected error in tool %s", name)
        return _error(name, "internal_error", "The railway data source failed unexpectedly.")

    return _error(name, "unknown_tool", f"Tool '{name}' is not available.")


def today_in_kolkata() -> str:
    from zoneinfo import ZoneInfo
    from datetime import datetime

    return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
