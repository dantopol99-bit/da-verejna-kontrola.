"""Normalizace raw -> core (blok 3): IČO, kurzy ČNB, typované částky, toky a vazby."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from pvk import raw
from pvk.castka import NeuplnaCastka
from pvk.normalizace import NCastka, normalizuj, over_ico
from pvk.normalizace.kurzy import KurzyCNB, parsuj_rok
from pvk.zdroje import zaregistruj_zdroje


@pytest.mark.parametrize(
    ("vstup", "ico", "duvod"),
    [
        ("00255513", "00255513", None),
        ("255513", "00255513", None),  # doplnění úvodních nul
        (255513, "00255513", None),
        ("CZ00255513", "00255513", None),
        ("00255514", None, "ico_neplatna_kontrolni_cislice"),
        ("Praha 4, Nusle", None, "ico_neplatny_format"),
        (None, None, None),
        ("", None, None),
    ],
)
def test_over_ico(vstup, ico, duvod):
    assert over_ico(vstup) == (ico, duvod)


ROK = """Datum|1 EUR|100 JPY|1 USD
02.01.2026|24,170|13,141|20,611
05.01.2026|24,195|13,226|20,742
Datum|1 EUR|1 USD
06.01.2026|24,200|20,800
"""


def test_kurzy_cnb_platny_kurz_k_datu():
    k = KurzyCNB()
    k.nacti_text(ROK)
    k._roky = {2026: True, 2025: True}
    assert k.kurz("EUR", date(2026, 1, 4)) == (Decimal("24.170"), date(2026, 1, 2))  # víkend: poslední vyhlášený
    assert k.kurz("EUR", date(2026, 1, 6)) == (Decimal("24.200"), date(2026, 1, 6))
    assert k.kurz("JPY", date(2026, 1, 5)) == (Decimal("0.13226"), date(2026, 1, 5))  # množství 100
    assert k.kurz("XYZ", date(2026, 1, 5)) is None
    assert k.kurz("EUR", date(2026, 3, 1)) is None  # bez vyhlášení v posledních 10 dnech
    assert "JPY" in parsuj_rok(ROK)


def test_castka_bez_typu_neprojde():
    with pytest.raises((NeuplnaCastka, ValueError)):
        NCastka("x", "neznamy_typ", Decimal(1), "CZK", "bez_dph", "celkem", date(2026, 1, 1)).over()


@pytest.fixture
def db_vlastni(test_db_url):
    """Normalizace commituje; vlastní dočasná databáze, aby neovlivnila ostatní testy sdílené databáze."""
    import uuid
    from urllib.parse import urlsplit, urlunsplit

    from pvk.db import migruj, pripoj

    c = urlsplit(test_db_url)
    admin = psycopg.connect(urlunsplit((c.scheme, c.netloc, "/postgres", c.query, c.fragment)), autocommit=True)
    jmeno = f"pvk_test_n_{uuid.uuid4().hex[:8]}"
    admin.execute(f'CREATE DATABASE "{jmeno}"')
    conn = pripoj(urlunsplit((c.scheme, c.netloc, "/" + jmeno, c.query, c.fragment)))
    migruj(conn)
    yield conn
    conn.close()
    admin.execute(f'DROP DATABASE IF EXISTS "{jmeno}" WITH (FORCE)')
    admin.close()


class Kotva:
    def __init__(self, zname):
        self.zname = set(zname)

    def subjekty_podle_ico(self, ica):
        return {i: (object() if i in self.zname else None) for i in ica}


def _vvz(conn, formular, zakazka, ico, **data):
    obsah = {"id": f"id-{formular}", "variableId": formular,
             "data": {"evCisloZakazkyVvz": zakazka, "druhFormulare": "16", "nazevZakazky": "Oprava mostu",
                      "datumUverejneniVvz": "2026-09-01T08:00:00+02:00", "zadavatele": [{"ico": ico}], **data}}
    return raw.zapis_zaznam(conn, zdroj="vvz", id_ve_zdroji=formular, url="https://api.vvz.nipez.cz/x",
                            cas_stazeni=datetime(2026, 9, 2, tzinfo=UTC), obsah=obsah, format="json")


def test_db_normalizace_tok_vazby_udalosti_a_vyjimky(db_vlastni):
    db = db_vlastni
    zaregistruj_zdroje(db)
    _vvz(db, "F1", "Z1", "00255513")
    _vvz(db, "F2", "Z1", "00255513", druhFormulare="38", zakazkaZrusena=True)  # dodatek + zrušení téže zakázky
    _vvz(db, "F3", "Z2", "00255514")  # neplatné IČO -> výjimka
    _vvz(db, "F4", "Z3", "00064581")  # platné, ale v kotvě nenalezeno -> výjimka
    db.commit()
    stat = normalizuj(db, ["vvz"], Kotva({"00255513"}), None)
    toky = db.execute("SELECT t.tok_id, t.platce_subjekt_id, t.subjekt_neurcen_duvod FROM core.tok_aktualni t").fetchall()
    assert len(toky) == 3  # F1 zakládá tok Z1, F2 se na něj navazuje
    vazby = db.execute("SELECT stav, skore, count(*) n FROM core.tok_zdroj_aktualni GROUP BY 1, 2").fetchall()
    assert [(v["stav"], v["skore"], v["n"]) for v in vazby] == [("dolozena", 1, 4)]
    typy = {r["typ"] for r in db.execute("SELECT typ FROM core.udalost_aktualni")}
    assert {"zverejneni", "dodatek", "zruseni"} <= typy
    vyjimky = {r["druh"] for r in db.execute("SELECT druh FROM core.normalizace_vyjimka")}
    assert vyjimky == {"ico_neplatna_kontrolni_cislice", "ico_nenalezeno_v_kotve"}
    assert db.execute("SELECT count(*) AS n FROM core.subjekt_aktualni").fetchone()["n"] == 1
    assert stat.toku[("vvz", "verejna_zakazka")] == 3
    # valid time = datum události ve světě, transaction time přidělila databáze
    r = db.execute("SELECT valid_from, recorded_from FROM core.zdrojovy_zaznam_aktualni LIMIT 1").fetchone()
    assert r["valid_from"] == date(2026, 9, 1) and r["recorded_from"] <= datetime.now(UTC)
    # opakovaný běh nic nezdvojí ani nepřepíše
    pred = db.execute("SELECT count(*) AS n FROM core.tok").fetchone()["n"]
    normalizuj(db, ["vvz"], Kotva({"00255513"}), None)
    assert db.execute("SELECT count(*) AS n FROM core.tok").fetchone()["n"] == pred
    assert {r["n"] for r in db.execute("SELECT count(*) AS n FROM core.pokryti_platcu")} == {1}


def test_db_cizi_mena_bez_kurzu_ma_priznak_a_dotace_stav_k_datu(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("""INSERT INTO core.castka (castka_id, zdrojovy_zaznam_id, typ, hodnota, mena, dph_rezim, perioda,
                      valid_from) SELECT gen_random_uuid(), gen_random_uuid(), 'smluvni', 1, 'EUR', 'bez_dph', 'celkem',
                      '2026-01-01'""")
    db.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("""INSERT INTO core.castka (castka_id, zdrojovy_zaznam_id, typ, hodnota, mena, dph_rezim, perioda,
                      valid_from) SELECT gen_random_uuid(), gen_random_uuid(), 'dotace_priznana', 1, 'CZK', 'mimo_dph',
                      'celkem', '2026-01-01'""")
    db.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):  # cizí měna bez údaje o přepočtu (zápis přes zapis_verzi)
        db.execute("""INSERT INTO core.castka (castka_id, zdrojovy_zaznam_id, typ, hodnota, mena, dph_rezim, perioda,
                      prepocet, valid_from) SELECT gen_random_uuid(), gen_random_uuid(), 'smluvni', 1, 'EUR',
                      'bez_dph', 'celkem', NULL, '2026-01-01'""")


def test_db_zrcadlo_jen_jako_vyvojovy_vzorek(db_vlastni):
    db = db_vlastni
    zaregistruj_zdroje(db)
    rid = raw.zapis_zaznam(db, zdroj="hlidac_statu_rs", id_ve_zdroji="1", url="https://www.hlidacstatu.cz/Detail/1",
                           cas_stazeni=datetime(2026, 9, 2, tzinfo=UTC), obsah={"a": 1}, format="html")
    assert db.execute("SELECT vyvojovy_vzorek FROM raw.zaznam WHERE id = %s", (rid,)).fetchone()["vyvojovy_vzorek"]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO raw.zaznam (zdroj, id_ve_zdroji, url, cas_stazeni, hash, format, obsah) VALUES "
                   "('hlidac_statu_rs', '2', 'u', now(), repeat('a', 64), 'html', '{}')")
