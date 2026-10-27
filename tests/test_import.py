from __future__ import annotations

from pathlib import Path

import pytest

from app.db import get_meta, session
from scripts.import_timetable import import_csv

HEADER = (
    "Train No,Train Name,SEQ,Station Code,Station Name,Arrival time,Departure Time,Distance,"
    "Source Station,Source Station Name,Destination Station,Destination Station Name\n"
)


def write_csv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "timetable_01012020.csv"
    path.write_text(HEADER + body)
    return path


def test_import_builds_normalised_tables(tmp_path):
    csv_path = write_csv(
        tmp_path,
        "1,TEST,1,AAA,ALPHA,00:00:00,06:00:00,0,AAA,ALPHA,BBB,BETA\n"
        "1,TEST,2,BBB,BETA,09:30:00,00:00:00,150,AAA,ALPHA,BBB,BETA\n"
        "2,SINGLE,1,AAA,ALPHA,00:00:00,10:00:00,0,AAA,ALPHA,AAA,ALPHA\n"
        "3,BAD,notanumber,AAA,ALPHA,00:00:00,10:00:00,0,AAA,ALPHA,BBB,BETA\n",
    )
    db = tmp_path / "out.db"
    stats = import_csv(csv_path, db)
    assert stats["trains"] == 1
    assert stats["stations"] == 2
    assert stats["stops"] == 2
    assert stats["skipped_rows"] == 2

    with session(db, read_only=True) as conn:
        meta = get_meta(conn)
        assert meta["dataset_date"] == "2020-01-01"
        row = conn.execute("SELECT * FROM train_stops WHERE seq = 1").fetchone()
        assert row["arrival"] is None
        assert row["departure"] == "06:00"


def test_import_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Train No,SEQ\n1,1\n")
    with pytest.raises(ValueError, match="missing required columns"):
        import_csv(path, tmp_path / "out.db")


def test_import_replaces_existing_database(tmp_path):
    csv_path = write_csv(
        tmp_path,
        "1,TEST,1,AAA,ALPHA,00:00:00,06:00:00,0,AAA,ALPHA,BBB,BETA\n"
        "1,TEST,2,BBB,BETA,09:30:00,00:00:00,150,AAA,ALPHA,BBB,BETA\n",
    )
    db = tmp_path / "out.db"
    import_csv(csv_path, db)
    import_csv(csv_path, db)
    with session(db, read_only=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM trains").fetchone()[0] == 1
