"""raw: neměnné, pouze INSERT; každý záznam má zdroj, ID ve zdroji, soubor/URL, čas stažení a hash."""

from datetime import UTC, datetime

import psycopg
import pytest

from pvk import raw

CAS = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def zdroj(db):
    raw.zajisti_zdroj(db, "test_zdroj", "Testovací zdroj", "Test", "https://example.invalid/")
    db.commit()
    return "test_zdroj"


def _zaznam(db, zdroj, obsah, **kw):
    return raw.zapis_zaznam(
        db,
        zdroj=zdroj,
        id_ve_zdroji=kw.pop("id_ve_zdroji", "A-1"),
        url=kw.pop("url", "https://example.invalid/a1"),
        cas_stazeni=CAS,
        obsah=obsah,
        format="json",
        **kw,
    )


def test_zapis_a_idempotence(db, zdroj):
    a = _zaznam(db, zdroj, {"x": 1, "y": "ž"})
    b = _zaznam(db, zdroj, {"y": "ž", "x": 1})  # stejný obsah, jiné pořadí klíčů -> stejný hash
    c = _zaznam(db, zdroj, {"x": 2, "y": "ž"})  # změna ve zdroji -> nový řádek
    assert a == b != c
    radky = db.execute(
        "SELECT hash, obsah FROM raw.zaznam WHERE zdroj = %s ORDER BY id", (zdroj,)
    ).fetchall()
    assert len(radky) == 2
    assert radky[0]["hash"] == raw.hash_zaznamu({"x": 1, "y": "ž"})


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE raw.zaznam SET id_ve_zdroji = 'jine'",
        "DELETE FROM raw.zaznam",
        "TRUNCATE raw.zaznam CASCADE",
        "UPDATE raw.stazeni SET http_status = 500",
        "DELETE FROM raw.stazeni",
        "UPDATE raw.zdroj SET nazev = 'x'",
        "DELETE FROM raw.zdroj WHERE kod = 'test_zdroj'",
    ],
)
def test_raw_je_pouze_pro_insert(db, zdroj, sql):
    _zaznam(db, zdroj, {"x": 1})
    raw.zapis_stazeni(db, zdroj=zdroj, url="https://example.invalid/", cas_stazeni=CAS, http_status=200,
                      sha256="0" * 64, velikost=1, soubor="x")
    db.commit()
    with pytest.raises(psycopg.Error) as e:
        db.execute(sql)
    assert e.value.sqlstate == "PV001"


@pytest.mark.parametrize("sloupec", ["zdroj", "id_ve_zdroji", "url", "cas_stazeni", "hash"])
def test_povinne_udaje_puvodu(db, zdroj, sloupec):
    hodnoty = {
        "zdroj": zdroj,
        "id_ve_zdroji": "B-1",
        "url": "https://example.invalid/b1",
        "cas_stazeni": CAS,
        "hash": "a" * 64,
    }
    hodnoty[sloupec] = None
    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute(
            "INSERT INTO raw.zaznam (zdroj, id_ve_zdroji, url, cas_stazeni, hash, format, obsah) "
            "VALUES (%(zdroj)s, %(id_ve_zdroji)s, %(url)s, %(cas_stazeni)s, %(hash)s, 'json', '{}')",
            hodnoty,
        )


def test_neplatny_hash_odmitnut(db, zdroj):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO raw.zaznam (zdroj, id_ve_zdroji, url, cas_stazeni, hash, format, obsah) "
            "VALUES (%s, 'C-1', 'https://example.invalid/', now(), 'neni-hash', 'json', '{}')",
            (zdroj,),
        )


def test_minimalizace_osobnich_udaju(db, zdroj):
    puvodni = {"id": "P-1", "jmeno": "Jan", "prijmeni": "Novák", "rokNarozeni": 1950, "castka": 1000}
    rid = _zaznam(db, zdroj, puvodni, id_ve_zdroji="P-1", redigovat=["jmeno", "prijmeni", "rokNarozeni"])
    radek = db.execute("SELECT hash, obsah, redigovano FROM raw.zaznam WHERE id = %s", (rid,)).fetchone()
    assert radek["obsah"] == {"id": "P-1", "castka": 1000}
    assert radek["redigovano"] == ["jmeno", "prijmeni", "rokNarozeni"]
    # hash zůstává hashem původního záznamu -> ověřitelnost proti zdrojovému souboru
    assert radek["hash"] == raw.hash_zaznamu(puvodni)


def test_stazeni_eviduje_i_neuspech(db, zdroj):
    sid = raw.zapis_stazeni(db, zdroj=zdroj, url="https://example.invalid/x", cas_stazeni=CAS,
                            http_status=None, chyba="ConnectionError: reset")
    radek = db.execute("SELECT * FROM raw.stazeni WHERE id = %s", (sid,)).fetchone()
    assert radek["chyba"].startswith("ConnectionError") and radek["sha256"] is None
    with pytest.raises(psycopg.errors.CheckViolation):
        raw.zapis_stazeni(db, zdroj=zdroj, url="https://example.invalid/y", cas_stazeni=CAS, http_status=None)
