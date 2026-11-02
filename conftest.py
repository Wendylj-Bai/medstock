"""
Safety net for ALL tests: no test may ever open the real database (data/medstock.db).

Tests must use a temporary database (pytest's tmp_path). If a test, or the app run by a
test, tries to connect to the real file, the test fails instead of changing your data.
"""

from pathlib import Path

import pytest

import db

REAL_DB = Path(db.DEFAULT_DB).resolve()


@pytest.fixture(autouse=True)
def never_touch_real_database(monkeypatch):
    real_connect = db.connect

    def guarded(path=db.DEFAULT_DB, *args, **kwargs):
        if Path(path).resolve() == REAL_DB:
            raise RuntimeError("A test tried to open the real database data/medstock.db. Use tmp_path instead.")
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(db, "connect", guarded)
