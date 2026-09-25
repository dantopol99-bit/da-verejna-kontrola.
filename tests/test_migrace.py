import shutil

import pytest

from pvk.db import ADRESAR_MIGRACI, ChybaMigrace, migruj, pripoj


def test_migrace_jsou_idempotentni(test_db_url):
    with pripoj(test_db_url) as conn:
        assert migruj(conn) == []


def test_zmenena_aplikovana_migrace_je_odmitnuta(test_db_url, tmp_path):
    for soubor in ADRESAR_MIGRACI.glob("*.sql"):
        shutil.copy(soubor, tmp_path / soubor.name)
    prvni = sorted(tmp_path.glob("*.sql"))[0]
    prvni.write_text(prvni.read_text(encoding="utf-8") + "\n-- dodatečná změna\n", encoding="utf-8")
    with pripoj(test_db_url) as conn, pytest.raises(ChybaMigrace):
        migruj(conn, tmp_path)


def test_schemata_existuji(db):
    schemata = {r["nspname"] for r in db.execute("SELECT nspname FROM pg_namespace")}
    assert {"raw", "core", "ind"} <= schemata


def test_entity_podle_metodiky(db):
    tabulky = {
        (r["table_schema"], r["table_name"])
        for r in db.execute(
            "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE'"
        )
    }
    ocekavane = {
        ("core", "zdrojovy_zaznam"), ("core", "subjekt"), ("core", "tok"), ("core", "tok_zdroj"),
        ("core", "castka"), ("core", "udalost"), ("core", "limit"), ("core", "metodika_verze"),
        ("ind", "indikator_vysledek"), ("raw", "zaznam"), ("raw", "stazeni"), ("raw", "zdroj"),
    }
    assert ocekavane <= tabulky


def test_vsechny_entity_core_jsou_bitemporalni(db):
    for r in db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'core' "
        "AND table_type = 'BASE TABLE' AND table_name <> 'entita'"
    ).fetchall():
        sloupce = {
            c["column_name"]
            for c in db.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'core' AND table_name = %s",
                (r["table_name"],),
            )
        }
        assert {"valid_from", "valid_to", "recorded_from", "recorded_to"} <= sloupce, r["table_name"]
