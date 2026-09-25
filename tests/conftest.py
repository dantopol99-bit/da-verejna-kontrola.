"""Společné fixtury.

Databázové testy běží v samostatné, dočasně vytvořené databázi (pvk_test_<náhodné>) na stejném
serveru jako DATABASE_URL (nebo PVK_TEST_DATABASE_URL). Vrstvy raw/core/ind nedovolují mazat,
proto se testovací data neuklízejí po řádcích – celá testovací databáze se na konci zahodí.
Bez dostupné databáze testy označené `db` selžou (nepřeskočí se), aby nemohly tiše projít.
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from pvk.db import migruj, pripoj

VYCHOZI_URL = "postgresql://pvk:pvk@localhost:55432/pvk"


def _url_s_databazi(url: str, databaze: str) -> str:
    casti = urlsplit(url)
    return urlunsplit((casti.scheme, casti.netloc, "/" + databaze, casti.query, casti.fragment))


@pytest.fixture(scope="session")
def test_db_url() -> str:
    zaklad = os.environ.get("PVK_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or VYCHOZI_URL
    jmeno = f"pvk_test_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(_url_s_databazi(zaklad, "postgres"), autocommit=True)
    except psycopg.OperationalError as e:
        pytest.fail(f"testy vyžadují PostgreSQL (make db): {e}")
    admin.execute(f'CREATE DATABASE "{jmeno}"')
    url = _url_s_databazi(zaklad, jmeno)
    with pripoj(url) as conn:
        migruj(conn)
    yield url
    admin.execute(f'DROP DATABASE IF EXISTS "{jmeno}" WITH (FORCE)')
    admin.close()


@pytest.fixture
def db(test_db_url):
    conn = pripoj(test_db_url)
    yield conn
    conn.rollback()
    conn.close()


def pytest_collection_modifyitems(items):
    for item in items:
        if "db" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.db)
