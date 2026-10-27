from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(BaseModel):
    """Where a piece of railway data came from and how fresh it is."""

    source: str
    source_url: str | None = None
    kind: Literal["scheduled", "live", "reservation"] = "scheduled"
    retrieved_at: str
    dataset_date: str | None = None
    note: str | None = None


class Station(BaseModel):
    code: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class TrainStop(BaseModel):
    sequence: int
    station_code: str
    station_name: str
    arrival: str | None = None
    departure: str | None = None
    halt_minutes: int | None = None
    distance_km: float | None = None
    day: int = 1


class TrainSummary(BaseModel):
    train_number: str
    train_name: str
    from_station: Station
    to_station: Station
    departure: str | None = None
    arrival: str | None = None
    duration_minutes: int | None = None
    distance_km: float | None = None
    stops: int | None = None
    running_days: list[str] | None = None


class TrainSchedule(BaseModel):
    train_number: str
    train_name: str
    stops: list[TrainStop]
    running_days: list[str] | None = None


class ComparisonRow(BaseModel):
    train_number: str
    train_name: str
    departure: str | None = None
    arrival: str | None = None
    duration_minutes: int | None = None
    stops: int | None = None
    distance_km: float | None = None


class ToolError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ToolResult(BaseModel):
    ok: bool
    tool: str
    data: Any = None
    error: ToolError | None = None
    provenance: Provenance | None = None
    notes: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_results: list[ToolResult] = Field(default_factory=list)
    sources: list[Provenance] = Field(default_factory=list)
    degraded: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    llm_provider: str
    llm_model: str | None = None
    railway_provider: str
    dataset: dict[str, Any]
    detail: str | None = None
