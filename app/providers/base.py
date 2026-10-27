from __future__ import annotations

from typing import Any, Protocol

from app.models import ComparisonRow, Provenance, Station, TrainSchedule, TrainSummary


class RailwayDataError(Exception):
    """Base class for expected, user-presentable railway data problems."""

    code = "railway_data_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class StationNotFound(RailwayDataError):
    code = "station_not_found"


class AmbiguousStation(RailwayDataError):
    code = "ambiguous_station"


class TrainNotFound(RailwayDataError):
    code = "train_not_found"


class FeatureUnsupported(RailwayDataError):
    code = "feature_unsupported"


class DatasetUnavailable(RailwayDataError):
    code = "dataset_unavailable"


class RailwayProvider(Protocol):
    """Interface every railway data source must implement.

    Live status, fares and availability are intentionally optional: a provider
    that cannot supply them must say so instead of guessing.
    """

    name: str

    def health(self) -> dict[str, Any]: ...

    def provenance(self) -> Provenance: ...

    def resolve_station(self, query: str) -> Station: ...

    def search_trains(
        self, from_station: str, to_station: str, journey_date: str
    ) -> list[TrainSummary]: ...

    def get_train_schedule(self, train_number: str) -> TrainSchedule: ...

    def get_train_route(self, train_number: str) -> TrainSchedule: ...

    def compare_trains(
        self,
        train_numbers: list[str],
        from_station: str | None,
        to_station: str | None,
        journey_date: str | None,
    ) -> list[ComparisonRow]: ...

    def get_live_status(self, train_number: str, journey_date: str | None = None) -> None:
        """Return live status when a configured provider supports it."""
        ...

    def get_fare_and_availability(self, **kwargs: Any) -> None: ...
