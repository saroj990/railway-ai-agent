from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.providers.local import LocalTimetableProvider  # noqa: E402
from app.sessions import SessionStore  # noqa: E402
from scripts.import_timetable import import_csv  # noqa: E402

FIXTURE_CSV = ROOT / "data" / "fixtures" / "demo_timetable.csv"


@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory) -> Path:
    db = tmp_path_factory.mktemp("db") / "fixture.db"
    import_csv(
        FIXTURE_CSV,
        db,
        source="FICTIONAL fixture data",
        source_url="",
        licence="Test fixture - not real railway data",
        dataset_date="2026-01-01",
        note="Fictional data for development and tests. Not real trains.",
    )
    return db


@pytest.fixture
def provider(fixture_db: Path) -> LocalTimetableProvider:
    return LocalTimetableProvider(fixture_db)


@pytest.fixture
def settings(fixture_db: Path) -> Settings:
    return Settings(llm_provider="none", railway_db_path=fixture_db)


@pytest.fixture
def sessions() -> SessionStore:
    return SessionStore(max_sessions=10, history_limit=12)
