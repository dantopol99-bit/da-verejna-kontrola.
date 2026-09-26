"""Párování smlouva (RS) – zakázka (VVZ) na vzorových datech (D-045)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pvk.parovani import ZakazkaP, parametry, paruj, paruj_jednu, shoda_predmetu, zakazky_z_oznameni
from pvk.zdroje.hlidac import parsuj_detail
from pvk.zdroje.vvz import parsuj_eforms

FIXTURES = Path(__file__).parent / "fixtures"
P = parametry()


@pytest.fixture(scope="module")
def smlouva():
    # vzorová smlouva RS: Horažďovice (00255513) – STAVEBNÍ SPOLEČNOST H a T (45023522), 20 068 576 Kč bez DPH
    return parsuj_detail((FIXTURES / "hs_detail_39673953.html").read_text(encoding="utf-8"), "39673953")


def zakazka(**zmeny) -> ZakazkaP:
    z = ZakazkaP(tok_klic="vvz:Z2026-000001", ev_cislo="Z2026-000001", ico_zadavatelu={"00255513"},
                 ico_dodavatelu={"45023522"}, datum_uzavreni=date(2026, 9, 24), cena_bez_dph=Decimal("20068576"),
                 predmet="Revitalizace sportovního areálu Lipky – 3. etapa")
    return replace(z, **zmeny)


def test_dolozena_shoda_odkazem_bt151(smlouva):
    s = paruj_jednu(zakazka(odkazy_rs={"39673953"}, ico_dodavatelu=set()), smlouva, P)
    assert (s.stav, s.skore, s.metoda) == ("dolozena", 1.0, "odkaz_bt151")


def test_dolozena_shoda_evidencnim_cislem_v_textu(smlouva):
    s = paruj_jednu(zakazka(ico_dodavatelu=set()), smlouva, P, text_smlouvy="Zakázka Z2026-000001 dle ZZVZ")
    assert (s.stav, s.metoda) == ("dolozena", "ev_cislo_v_rs")
    # evidenční číslo bez shody IČO zadavatele doložení nestačí
    assert paruj_jednu(zakazka(ico_zadavatelu={"00064581"}, ico_dodavatelu=set()), smlouva, P,
                       text_smlouvy="Z2026-000001") is None


def test_pravdepodobna_shoda_se_skore_pod_jednou(smlouva):
    s = paruj_jednu(zakazka(), smlouva, P)
    assert s.stav == "pravdepodobna" and s.metoda == "heuristika_ico_datum_castka_predmet"
    assert 0.9 <= s.skore <= P["max_skore"] < 1  # skóre 1 je vyhrazeno doloženým vazbám (D-006)


def test_castka_s_dph_se_prepocte(smlouva):
    s = paruj_jednu(zakazka(cena_bez_dph=Decimal("24282977") / Decimal("1.21")), smlouva, P)
    assert s.stav == "pravdepodobna" and "částka 1.00" in s.zduvodneni


@pytest.mark.parametrize(
    "zmena",
    [
        {"ico_dodavatelu": {"00064581"}},  # jiný dodavatel
        {"datum_uzavreni": date(2026, 3, 1), "cena_bez_dph": Decimal("1000"), "predmet": "Nákup papíru"},
    ],
)
def test_bez_shody_ico_nebo_pod_prahem_neni_shoda(smlouva, zmena):
    assert paruj_jednu(zakazka(**zmena), smlouva, P) is None


def test_prah_a_vahy(smlouva):
    # jen IČO + datum (bez částky a předmětu): 0,4 + 0,25 = 0,65 < práh 0,70
    assert paruj_jednu(zakazka(cena_bez_dph=None, predmet=None), smlouva, P) is None
    # IČO + datum + předmět: 0,4 + 0,25 + 0,1 = 0,75
    s = paruj_jednu(zakazka(cena_bez_dph=None), smlouva, P)
    assert s is not None and s.skore == pytest.approx(0.75, abs=0.01)


def test_predmet_bez_diakritiky():
    assert shoda_predmetu("Revitalizace areálu Lipky", "REVITALIZACE AREALU LIPKY", P) == 1.0
    assert shoda_predmetu("Oprava mostu", "Nákup papíru", P) == 0.0


def test_paruj_dava_prednost_dolozene(smlouva):
    jina = replace(smlouva, id_verze="1")
    shody = paruj([zakazka(odkazy_rs={"39673953"})], [jina, smlouva], P)
    assert [(s.id_verze, s.stav) for s in shody] == [("39673953", "dolozena")]


def test_zakazky_z_oznameni_vvz():
    data = json.loads((FIXTURES / "vvz_F2025-035449.json").read_text(encoding="utf-8"))
    ozn = parsuj_eforms(data["souhrn"], data["deti"])
    zakazky = zakazky_z_oznameni(ozn)
    assert zakazky and all(z.ico_zadavatelu for z in zakazky)
    assert any(z.odkazy_rs for z in zakazky) or all(z.cena_bez_dph is not None for z in zakazky)
