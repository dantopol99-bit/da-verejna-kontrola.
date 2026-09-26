"""Souhrny v rámci jednoho zdroje a typu částky: pokrytí, podíl heuristiky, rozpětí (D-046) a publikační brána."""

from __future__ import annotations

from datetime import UTC, date, datetime

from pvk import publikace, raw
from pvk.core import klic_entity, zajisti_metodiku, zapis_entitu
from pvk.souhrny import souhrn_subjektu
from pvk.zdroje import zaregistruj_zdroje


def _pripravena_data(db):
    """Tok zakázky 00255513 -> 45023522: částka 100 z doloženého záznamu a 50 ze záznamu navázaného
    jen pravděpodobnou vazbou (heuristická deduplikace)."""
    zaregistruj_zdroje(db)
    m = zajisti_metodiku(db, {"kod": "t-souhrn", "popis": "t", "platnost_od": "2020-01-01", "parametry": {}})
    for ico in ("00255513", "45023522"):
        zapis_entitu(db, "subjekt", ico, {"ico": ico}, date(1990, 1, 1))
    tok = zapis_entitu(db, "tok", "vvz:Z1", {"druh": "verejna_zakazka",
                                             "platce_subjekt_id": str(klic_entity("subjekt", "00255513")),
                                             "prijemce_subjekt_id": str(klic_entity("subjekt", "45023522"))},
                       date(2026, 9, 1))
    for i, (stav, skore, hodnota) in enumerate([("dolozena", 1, 100), ("pravdepodobna", 0.8, 50)]):
        rid = raw.zapis_zaznam(db, zdroj="vvz", id_ve_zdroji=f"F{i}", url="https://api.vvz.nipez.cz/x",
                               cas_stazeni=datetime(2026, 9, 2, tzinfo=UTC), obsah={"i": i}, format="json")
        zz = zapis_entitu(db, "zdrojovy_zaznam", f"vvz:F{i}", {"raw_zaznam_id": rid, "zdroj": "vvz",
                                                               "id_ve_zdroji": f"F{i}", "druh": "zakazka", "url": "u"},
                          date(2026, 9, 1))
        zapis_entitu(db, "tok_zdroj", f"t{i}", {"tok_id": str(tok), "zdrojovy_zaznam_id": str(zz), "stav": stav,
                                                "metoda": "test", "skore": skore, "metodika_verze_id": str(m)},
                     date(2026, 9, 1))
        zapis_entitu(db, "castka", f"c{i}", {"tok_id": str(tok), "zdrojovy_zaznam_id": str(zz), "typ": "vysoutezena",
                                             "hodnota": hodnota, "mena": "CZK", "dph_rezim": "bez_dph",
                                             "perioda": "celkem"}, date(2026, 9, 5))
    db.commit()


def test_souhrn_s_podilem_heuristiky_a_rozpetim(db_vlastni):
    _pripravena_data(db_vlastni)
    s = souhrn_subjektu(db_vlastni, "45023522", "vvz", "vysoutezena", date(2026, 1, 1), date(2027, 1, 1))
    assert s["podil_heuristicke_deduplikace"] == round(50 / 150, 4)
    assert s["rozpeti"] == {"dolni_se_shodou": "100.00", "horni_bez_shody": "150.00"}
    assert s["hodnota"] == "100.00" and s["pocet_castek"] == 2
    assert s["pokryti"] == {"toku": 1, "s_castkou_typu": 1, "s_ico_obou_stran": 1}
    metodiky = publikace.nacti_metodiky()
    assert publikace.over_vystup(s, metodiky, "test") == []
    # souhrn bez podílu heuristiky neprojde
    bez_podilu = {k: v for k, v in s.items() if k != "podil_heuristicke_deduplikace"}
    assert "SOUHRN_BEZ_PODILU_HEURISTIKY" in {p.kod for p in publikace.over_vystup(bez_podilu, metodiky, "test")}
    # nad prahem bez rozpětí neprojde
    assert "SOUHRN_BEZ_ROZPETI" in {p.kod for p in publikace.over_vystup({**s, "rozpeti": None}, metodiky, "test")}
    # jiný typ částky nebo zdroj se do souhrnu nezapočte
    assert souhrn_subjektu(db_vlastni, "45023522", "vvz", "smluvni", date(2026, 1, 1), date(2027, 1, 1))["pocet_castek"] == 0
    assert souhrn_subjektu(db_vlastni, "45023522", "red", "vysoutezena", date(2026, 1, 1),
                           date(2027, 1, 1))["pocet_castek"] == 0


def test_souhrn_pod_prahem_bez_rozpeti():
    s = {"druh": "souhrn", "typ": "smluvni", "mena": "CZK", "dph_rezim": "bez_dph", "perioda": "celkem",
         "podil_heuristicke_deduplikace": 0.01, "metodika_verze": "souhrny-2026.09"}
    assert publikace.over_vystup(s, publikace.nacti_metodiky(), "test") == []
