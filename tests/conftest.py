from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    from clusterdetect import db

    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    return path
