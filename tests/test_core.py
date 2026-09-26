"""core: bitemporální model. Nic se nepřepisuje, změna = nová verze."""

import uuid
from datetime import date

import psycopg
import pytest

from pvk import raw
from pvk.core import subjekt_pro_ico, zajisti_metodiku, zapis_verzi


def aktualni(db, tabulka, klic_sloupec, klic):
    return db.execute(
        f"SELECT * FROM core.{tabulka} WHERE {klic_sloupec} = %s AND recorded_to = 'infinity' ORDER BY valid_from",
        (klic,),
    ).fetchall()


def vse(db, tabulka, klic_sloupec, klic):
    return db.execute(f"SELECT * FROM core.{tabulka} WHERE {klic_sloupec} = %s ORDER BY verze_id", (klic,)).fetchall()


def test_nova_verze_nerusi_historii(db):
    klic = zapis_verzi(db, "limit", {
        "kod": "rs_hranice", "popis": "Hranice zveřejnění v RS", "hodnota": 50000, "jednotka": "CZK",
        "dph_rezim": "bez_dph", "pravni_zaklad": "zákon 340/2015 Sb., § 3 odst. 2 písm. i)",
    }, date(2016, 7, 1))
    db.commit()
    zapis_verzi(db, "limit", {
        "limit_id": str(klic), "kod": "rs_hranice", "popis": "Hranice zveřejnění v RS", "hodnota": 60000,
        "jednotka": "CZK", "dph_rezim": "bez_dph", "pravni_zaklad": "hypotetická novela",
    }, date(2027, 1, 1))
    db.commit()

    historie = vse(db, "limit", "limit_id", klic)
    assert len(historie) == 3  # původní (uzavřená), zbytek do 2027, nová od 2027
    assert historie[0]["recorded_to"] != date.max and historie[0]["valid_to"] == date.max
    platne = aktualni(db, "limit", "limit_id", klic)
    assert [(r["hodnota"], r["valid_from"], r["valid_to"]) for r in platne] == [
        (50000, date(2016, 7, 1), date(2027, 1, 1)),
        (60000, date(2027, 1, 1), date.max),
    ]
    # "jak jsme to věděli" před druhým zápisem: jediná verze s hodnotou 50000 platná navždy
    drive = db.execute(
        "SELECT hodnota, valid_to FROM core.limit WHERE limit_id = %s "
        "AND recorded_from <= %s AND %s < recorded_to",
        (klic, historie[0]["recorded_from"], historie[0]["recorded_from"]),
    ).fetchall()
    assert [(r["hodnota"], r["valid_to"]) for r in drive] == [(50000, date.max)]


def test_vlozeni_uprostred_intervalu_rozdeli_verzi(db):
    klic = zapis_verzi(db, "metodika_verze", {"kod": "t-rozdel", "popis": "a", "parametry": {"v": 1}}, date(2020, 1, 1))
    db.commit()
    zapis_verzi(db, "metodika_verze", {"metodika_verze_id": str(klic), "kod": "t-rozdel", "popis": "b",
                                       "parametry": {"v": 2}}, date(2021, 1, 1), date(2022, 1, 1))
    db.commit()
    platne = aktualni(db, "metodika_verze", "metodika_verze_id", klic)
    assert [(r["popis"], r["valid_from"], r["valid_to"]) for r in platne] == [
        ("a", date(2020, 1, 1), date(2021, 1, 1)),
        ("b", date(2021, 1, 1), date(2022, 1, 1)),
        ("a", date(2022, 1, 1), date.max),
    ]


def test_opakovany_stejny_zapis_nevytvori_verzi(db):
    klic = zapis_verzi(db, "metodika_verze", {"kod": "t-idem", "popis": "a", "parametry": {"v": 1}}, date(2020, 1, 1))
    db.commit()
    zapis_verzi(db, "metodika_verze", {"metodika_verze_id": str(klic), "kod": "t-idem", "popis": "a",
                                       "parametry": {"v": 1}}, date(2020, 1, 1))
    db.commit()
    assert len(vse(db, "metodika_verze", "metodika_verze_id", klic)) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE core.metodika_verze SET popis = 'prepsano' WHERE metodika_verze_id = %s",
        "UPDATE core.metodika_verze SET valid_to = '2030-01-01' WHERE metodika_verze_id = %s",
        "DELETE FROM core.metodika_verze WHERE metodika_verze_id = %s",
    ],
)
def test_prepis_a_mazani_zakazano(db, sql):
    kod = f"t-prepis-{uuid.uuid4().hex[:8]}"
    klic = zapis_verzi(db, "metodika_verze", {"kod": kod, "popis": "a", "parametry": {}}, date(2020, 1, 1))
    db.commit()
    with pytest.raises(psycopg.Error) as e:
        db.execute(sql, (klic,))
    assert e.value.sqlstate == "PV002"


def test_uzavrenou_verzi_nelze_zmenit(db):
    klic = zapis_verzi(db, "metodika_verze", {"kod": "t-uzavrena", "popis": "a", "parametry": {}}, date(2020, 1, 1))
    db.commit()
    zapis_verzi(db, "metodika_verze", {"metodika_verze_id": str(klic), "kod": "t-uzavrena", "popis": "b",
                                       "parametry": {}}, date(2020, 1, 1))
    db.commit()
    with pytest.raises(psycopg.Error) as e:
        db.execute(
            "UPDATE core.metodika_verze SET recorded_to = now() WHERE metodika_verze_id = %s "
            "AND recorded_to <> 'infinity'",
            (klic,),
        )
    assert e.value.sqlstate == "PV002"


def test_prekryvajici_se_aktualni_verze_nelze_vlozit_primo(db):
    klic = zapis_verzi(db, "metodika_verze", {"kod": "t-prekryv", "popis": "a", "parametry": {}}, date(2020, 1, 1))
    db.commit()
    with pytest.raises(psycopg.errors.ExclusionViolation):
        db.execute(
            "INSERT INTO core.metodika_verze (metodika_verze_id, kod, popis, parametry, valid_from) "
            "VALUES (%s, 't-prekryv', 'b', '{}', '2021-01-01')",
            (klic,),
        )


def test_recorded_cas_prideluje_databaze(db):
    db.execute(
        "INSERT INTO core.entita (id, typ) VALUES ('00000000-0000-0000-0000-00000000000a', 'metodika_verze')"
    )
    db.execute(
        "INSERT INTO core.metodika_verze (metodika_verze_id, kod, popis, parametry, valid_from, recorded_from, recorded_to) "
        "VALUES ('00000000-0000-0000-0000-00000000000a', 't-cas', 'a', '{}', '2020-01-01', '1999-01-01', '2000-01-01')"
    )
    r = db.execute(
        "SELECT recorded_from = now() AS ted, recorded_to = 'infinity' AS otevrena FROM core.metodika_verze "
        "WHERE kod = 't-cas'"
    ).fetchone()
    assert r["ted"] and r["otevrena"]


def test_subjekt_je_jen_ico_s_kontrolou(db):
    s = subjekt_pro_ico(db, "00255513")
    assert subjekt_pro_ico(db, "00255513") == s
    sloupce = {r["column_name"] for r in db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='core' AND table_name='subjekt'")}
    assert sloupce == {"verze_id", "subjekt_id", "entita_typ", "ico", "valid_from", "valid_to",
                       "recorded_from", "recorded_to"}
    with pytest.raises(psycopg.errors.CheckViolation):
        zapis_verzi(db, "subjekt", {"ico": "00255514"}, date(2020, 1, 1))


def _zdrojovy_zaznam(db):
    raw.zajisti_zdroj(db, "test_core", "Test", "Test", "https://example.invalid/")
    rid = raw.zapis_zaznam(db, zdroj="test_core", id_ve_zdroji="1", url="https://example.invalid/1",
                           cas_stazeni="2026-09-25T00:00:00Z", obsah={"a": 1}, format="json")
    return zapis_verzi(db, "zdrojovy_zaznam", {"raw_zaznam_id": rid, "zdroj": "test_core", "id_ve_zdroji": "1",
                                              "druh": "smlouva", "url": "https://example.invalid/1"},
                       date(2026, 1, 1))


def test_castka_vyzaduje_typ_dph_menu_periodu(db):
    zz = _zdrojovy_zaznam(db)
    zaklad = {"zdrojovy_zaznam_id": str(zz), "typ": "smluvni", "hodnota": 100, "mena": "CZK",
              "dph_rezim": "bez_dph", "perioda": "celkem"}
    zapis_verzi(db, "castka", zaklad, date(2026, 1, 1))
    for pole in ("typ", "mena", "dph_rezim", "perioda"):
        db.execute("SAVEPOINT s")
        with pytest.raises(psycopg.errors.NotNullViolation):
            zapis_verzi(db, "castka", {**zaklad, pole: None}, date(2026, 1, 1))
        db.execute("ROLLBACK TO SAVEPOINT s")
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        zapis_verzi(db, "castka", {**zaklad, "typ": "nejaka"}, date(2026, 1, 1))


def test_tok_zdroj_stav_a_skore(db):
    zz = _zdrojovy_zaznam(db)
    m = zajisti_metodiku(db, {"kod": "t-tz", "popis": "t", "platnost_od": "2020-01-01", "parametry": {}})
    tok = zapis_verzi(db, "tok", {"druh": "smlouva", "subjekt_neurcen_duvod": "test"}, date(2026, 1, 1))
    zaklad = {"tok_id": str(tok), "zdrojovy_zaznam_id": str(zz), "metoda": "odkaz_bt151",
              "metodika_verze_id": str(m)}
    zapis_verzi(db, "tok_zdroj", {**zaklad, "stav": "dolozena", "skore": 1}, date(2026, 1, 1))
    zapis_verzi(db, "tok_zdroj", {**zaklad, "stav": "pravdepodobna", "skore": 0.82,
                                  "metoda": "heuristika_ico_datum_castka"}, date(2026, 1, 1))
    for stav, skore in (("dolozena", 0.9), ("pravdepodobna", 1)):
        db.execute("SAVEPOINT s")
        with pytest.raises(psycopg.errors.CheckViolation):
            zapis_verzi(db, "tok_zdroj", {**zaklad, "stav": stav, "skore": skore}, date(2026, 1, 1))
        db.execute("ROLLBACK TO SAVEPOINT s")


def test_zapis_verzi_jen_pro_entity_core(db):
    with pytest.raises(psycopg.Error):
        db.execute("SELECT core.zapis_verzi('raw.zaznam'::regclass, '{}'::jsonb, '2020-01-01')")


def test_oprava_novou_verzi_vcetne_intervalu(db):
    """D-048: oprava uzavře všechny aktuální verze (i zbytek starého intervalu) a vloží opravenou verzi."""
    from pvk.core import aktualni_atributy, oprav_entitu

    tok = zapis_verzi(db, "tok", {"druh": "dotace", "subjekt_neurcen_duvod": "test"}, date(202, 4, 23))
    db.commit()
    zapis_verzi(db, "tok", {"tok_id": str(tok), "druh": "dotace", "subjekt_neurcen_duvod": "test"}, date(2026, 6, 24))
    db.commit()
    assert db.execute("SELECT count(*) AS n FROM core.tok_aktualni WHERE tok_id = %s", (tok,)).fetchone()["n"] == 2
    n = oprav_entitu(db, "tok", tok, [(aktualni_atributy(db, "tok", tok), date(2026, 6, 24), None)], "chybné datum ve zdroji")
    db.commit()
    assert n == 1
    aktualni = db.execute("SELECT valid_from FROM core.tok_aktualni WHERE tok_id = %s", (tok,)).fetchall()
    assert [r["valid_from"] for r in aktualni] == [date(2026, 6, 24)]
    assert db.execute("SELECT count(*) AS n FROM core.tok WHERE tok_id = %s", (tok,)).fetchone()["n"] == 4  # nic nesmazáno
    o = db.execute("SELECT duvod, jsonb_array_length(puvodni) AS p FROM core.oprava WHERE entita_id = %s", (tok,)).fetchone()
    assert (o["duvod"], o["p"]) == ("chybné datum ve zdroji", 2)
    # stejný stav podruhé nic nezapíše; bez důvodu oprava neprojde
    assert oprav_entitu(db, "tok", tok, [(aktualni_atributy(db, "tok", tok), date(2026, 6, 24), None)], "znovu") == 0
    with pytest.raises(psycopg.Error):
        oprav_entitu(db, "tok", tok, [(aktualni_atributy(db, "tok", tok), date(2026, 1, 1), None)], "")
