"""Normalizace raw -> core (blok 3): IČO, kurzy ČNB, typované částky, toky a vazby."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from pvk import raw
from pvk.castka import NeuplnaCastka
from pvk.core import klic_entity
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


def _detail(conn, formular, loty):
    """Detail formuláře eForms se zadanými částmi (BT-137-Lot) a vítězem každé části."""
    orgs = [{"ND-Company": {"OPT-200-Organization-Company": f"ORG-{i}", "ND-CompanyLegalEntity": [
        {"BT-501-Organization-Company": ico}]}} for i, ico in enumerate(["00255513", "45023522", "25400339"])]
    root = {"BT-03-notice": "result", "ND-ContractingParty": [{"ND-Buyer": {"OPT-300-Procedure-Buyer": "ORG-0"}}],
            "ND-Lot": [{"BT-137-Lot": lot} for lot in loty],
            "ND-RootExtension": {"ND-Organizations": {"ND-Organization": orgs}, "ND-NoticeResult": {
                "ND-TenderingParty": [{"OPT-210-Tenderer": f"TPA-{i}", "ND-Tenderer": [{"OPT-300-Tenderer": f"ORG-{i + 1}"}]}
                                      for i in range(len(loty))],
                "ND-LotTender": [{"OPT-321-Tender": f"TEN-{i}", "OPT-310-Tender": f"TPA-{i}", "BT-13714-Tender": lot,
                                  "BT-720-Tender": {"_value": 100.0 * (i + 1), "_currencyID": "CZK"}}
                                 for i, lot in enumerate(loty)],
                "ND-LotResult": [{"BT-13713-LotResult": lot, "BT-142-LotResult": "selec-w",
                                  "ND-LotResultTenderReference": [{"OPT-320-LotResult": f"TEN-{i}"}]}
                                 for i, lot in enumerate(loty)]}}}
    return raw.zapis_zaznam(conn, zdroj="vvz_detail", id_ve_zdroji=formular, url="https://api.vvz.nipez.cz/d",
                            cas_stazeni=datetime(2026, 9, 3, tzinfo=UTC), format="json",
                            obsah={"formular": formular, "submission": f"id-{formular}", "deti": [{"data": {"ND-Root": root}}]})


def test_db_zakazka_s_castmi_je_tok_za_cast_a_oprava_bez_mazani(db_vlastni):
    db = db_vlastni
    zaregistruj_zdroje(db)
    _vvz(db, "F1", "Z9", "00255513")
    db.commit()
    kotva = Kotva({"00255513", "45023522", "25400339"})
    normalizuj(db, ["vvz", "vvz_detail"], kotva, None)
    assert [r["n"] for r in db.execute("SELECT count(*) AS n FROM core.tok_aktualni")] == [1]  # zatím celá zakázka
    _vvz(db, "F2", "Z9", "00255513", druhFormulare="29")
    _detail(db, "F2", ["LOT-0001", "LOT-0002"])  # výsledek: zakázka má dvě části s různými dodavateli
    db.commit()
    stat = normalizuj(db, ["vvz", "vvz_detail"], kotva, None)
    toky = db.execute("SELECT predmet, prijemce_subjekt_id FROM core.tok_aktualni ORDER BY predmet").fetchall()
    assert len(toky) == 2 and all(t["predmet"].endswith(("LOT-0001", "LOT-0002")) for t in toky)
    assert len({t["prijemce_subjekt_id"] for t in toky}) == 2  # každá část má svého dodavatele
    # tok celé zakázky zůstal v historii (uzavřená verze) a má záznam o ukončení s náhradou
    ukonceni = db.execute("SELECT tabulka, cardinality(nahrazeno) AS n FROM core.ukonceni_entity WHERE tabulka = 'tok'").fetchall()
    assert [(u["tabulka"], u["n"]) for u in ukonceni] == [("tok", 2)] and stat.ukonceno["tok"] == 1
    assert db.execute("SELECT count(*) AS n FROM core.tok WHERE tok_id = %s",
                      (klic_entity("tok", "vvz:Z9"),)).fetchone()["n"] == 1
    # oba formuláře zakázky (souhrn F1, F2 a detail F2) jsou navázané na obě části: 3 záznamy × 2 části
    assert db.execute("SELECT count(*) AS n FROM core.tok_zdroj_aktualni").fetchone()["n"] == 6
    # opakovaný běh: žádná nová verze
    pred = [db.execute(f"SELECT count(*) AS n FROM core.{t}").fetchone()["n"] for t in ("tok", "tok_zdroj", "castka", "udalost")]
    normalizuj(db, ["vvz", "vvz_detail"], kotva, None)
    assert [db.execute(f"SELECT count(*) AS n FROM core.{t}").fetchone()["n"]
            for t in ("tok", "tok_zdroj", "castka", "udalost")] == pred
