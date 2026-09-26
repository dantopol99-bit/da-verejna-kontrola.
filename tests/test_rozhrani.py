"""Rozhraní pro kotvu (schéma pvk.verejne_penize 1.0) a kontrolní sada (D-055)."""

from __future__ import annotations

import csv
from datetime import date

from pvk import publikace
from pvk.kontrolni_sada import SLOUPCE, radky, zapis
from pvk.rozhrani import SCHEMA, SCHEMA_VERZE, verejne_penize
from tests.test_souhrny import _pripravena_data


class _Kotva:
    def __init__(self, fo: bool):
        self.fo = fo

    def subjekt_podle_ico(self, ico):
        return type("S", (), {"je_fyzicka_osoba": self.fo})()


def test_vystup_pro_kotvu(db_vlastni):
    _pripravena_data(db_vlastni)
    v = verejne_penize(db_vlastni, "00255513", date(2026, 9, 26))
    assert (v["schema"], v["schema_verze"], v["vydano"]) == (SCHEMA, SCHEMA_VERZE, True)
    assert {"k_datu", "stav_poznani", "obdobi_od", "obdobi_do", "zakazky_jako_zadavatel", "zakazky_jako_dodavatel",
            "dotace", "indikatory", "vynechano", "upozorneni"} <= set(v)
    # souhrn stojí zčásti na pravděpodobné vazbě -> párování není ověřené, brána ho nepustí (D-049)
    assert v["zakazky_jako_zadavatel"] == []
    assert any("PAROVANI_NEOVERENE" in x["duvod"] for x in v["vynechano"])
    # každá vydaná položka nese typ částky a pokrytí a projde bránou
    for s in v["zakazky_jako_zadavatel"] + v["zakazky_jako_dodavatel"] + v["dotace"]:
        assert s["typ"] and s["pokryti"] and "podil_heuristicke_deduplikace" in s
    assert all(publikace.over_text(t) == [] for t in v["upozorneni"])


def test_profil_fyzicke_osoby_a_nenalezene_ico_se_nevydava(db_vlastni):
    _pripravena_data(db_vlastni)
    assert verejne_penize(db_vlastni, "00255513", kotva=_Kotva(fo=True))["vydano"] is False
    v = verejne_penize(db_vlastni, "00064581")
    assert v["vydano"] is False and "není to nulová hodnota" in v["duvod"]


def test_kontrolni_sada_ma_sloupec_potvrzeno_a_ceka_na_zdroj(db_vlastni, tmp_path):
    r = radky(db_vlastni)
    assert all(x["potvrzeno"] == "" for x in r)
    assert any(x["navrh_verdiktu"].startswith("čeká na zdroj") for x in r)
    cesta = zapis(r, tmp_path / "sada.csv")
    with cesta.open(encoding="utf-8") as f:
        assert tuple(csv.DictReader(f).fieldnames) == SLOUPCE
    assert publikace.over_text(cesta.read_text(encoding="utf-8")) == []
