import shutil

import psycopg
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
        "AND table_type = 'BASE TABLE' AND table_name NOT IN ('entita', 'normalizace_beh', 'normalizace_vyjimka', 'ukonceni_entity', 'oprava')"
    ).fetchall():
        sloupce = {
            c["column_name"]
            for c in db.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'core' AND table_name = %s",
                (r["table_name"],),
            )
        }
        assert {"valid_from", "valid_to", "recorded_from", "recorded_to"} <= sloupce, r["table_name"]


def test_evidence_normalizace_je_pouze_pro_insert(db):
    """Evidence běhů a výjimek normalizace nejsou entity (nejsou bitemporální), ale nic se v nich nepřepisuje."""
    db.execute("INSERT INTO core.normalizace_beh (parametry) VALUES ('{}')")
    for prikaz in ("DELETE FROM core.normalizace_beh", "UPDATE core.normalizace_beh SET parametry = '{}'",
                   "TRUNCATE core.normalizace_vyjimka"):
        db.execute("SAVEPOINT s")
        with pytest.raises(psycopg.Error) as e:
            db.execute(prikaz)
        assert e.value.sqlstate == "PV001", prikaz
        db.execute("ROLLBACK TO SAVEPOINT s")
