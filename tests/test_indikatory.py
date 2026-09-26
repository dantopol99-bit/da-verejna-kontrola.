"""Indikátory (blok 4): pravidla na vzorových datech, čekající indikátory, texty bez hodnotících výrazů."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from pvk import indikatory as ind
from pvk import publikace


def test_pracovni_dny_a_svatky():
    assert date(2026, 4, 3) in ind.svatky(2026) and date(2026, 4, 6) in ind.svatky(2026)  # Velký pátek, Vel. pondělí
    assert ind.pracovni_dny(date(2026, 4, 2), date(2026, 4, 7)) == 1  # pá a po svátek, víkend
    assert ind.pracovni_dny(date(2026, 9, 21), date(2026, 9, 28)) == 4  # 28. 9. je svátek


def test_jedina_nabidka_jen_se_znamym_poctem_a_pod_minimem_se_nepocita():
    f = [{"zadavatel": "00255513", "cpv": "45000000", "typ": "result", "nabidky": [1, 1, 3], "zahajeni": date(2026, 9, 1)},
         {"zadavatel": "00255513", "cpv": "45200000", "typ": "result", "nabidky": [1, 2], "zahajeni": date(2026, 9, 2)},
         {"zadavatel": "00255513", "cpv": "45200000", "typ": "competition", "nabidky": [], "zahajeni": date(2026, 9, 3)}]
    v = ind.jedina_nabidka(f, {})
    assert len(v) == 1 and v[0].pocet_pripadu == 5 and v[0].hodnota == Decimal("0.6") and v[0].srovnavaci_skupina == "CPV 45"
    assert ind.nad_minimem(v, {"min_pocet_pripadu": 6}) == []


def test_velikostni_skupina():
    pasma = ind.metodika("koncentrace_dodavatele")["parametry"]["velikostni_skupiny"]
    assert ind.velikostni_skupina(Decimal("500000"), pasma) == "do 1 mil. Kč"
    assert ind.velikostni_skupina(Decimal("250000000"), pasma) == "nad 100 mil. Kč"


def test_ceka_na_zdroj_deleni_pod_limit():
    s = [{"ico_zadavatele": "00255513", "ico_dodavatele": "45023522", "datum": date(2026, 1, 5), "hodnota_bez_dph": Decimal(1900000)},
         {"ico_zadavatele": "00255513", "ico_dodavatele": "45023522", "datum": date(2026, 2, 20), "hodnota_bez_dph": Decimal(1500000)},
         {"ico_zadavatele": "00255513", "ico_dodavatele": "45023522", "datum": date(2026, 9, 1), "hodnota_bez_dph": Decimal(100000)},
         {"ico_zadavatele": "00064581", "ico_dodavatele": "45023522", "datum": date(2026, 1, 5), "hodnota_bez_dph": Decimal(2900000)}]
    signaly = ind.deleni_pod_limit(s, Decimal(3000000), 90)
    assert [(x["ico_zadavatele"], x["pocet_smluv"], x["soucet_bez_dph"]) for x in signaly] == [("00255513", 2, Decimal(3400000))]


def test_ceka_na_zdroj_pasmo_kotvy():
    z = [{"ico_zadavatele": "A", "ico_dodavatele": "X", "hodnota": Decimal(80)},
         {"ico_zadavatele": "A", "ico_dodavatele": "Y", "hodnota": Decimal(20)}]
    r = ind.dodavatel_pasmo_kotvy(z, {"X": "sledovane", "Y": "bezne"}, {"sledovane"})
    assert r["A"] == {"pocet_pripadu": 2, "zaklad": Decimal(100), "podil": Decimal("0.8")}


def test_ceka_na_zdroj_zmena_struktury():
    zak = [{"ico_dodavatele": "45023522", "datum": date(2026, 6, 1)}, {"ico_dodavatele": "25400339", "datum": date(2026, 6, 1)}]
    zm = [{"ico": "45023522", "datum": date(2026, 5, 10), "druh": "statutarni_organ"},
          {"ico": "25400339", "datum": date(2025, 1, 1), "druh": "sidlo"}]
    assert ind.zmena_struktury(zak, zm, 90) == [{"ico_dodavatele": "45023522", "datum": date(2026, 6, 1),
                                                 "zmeny": ["statutarni_organ"]}]


@pytest.mark.parametrize("kod", ind.CEKAJICI)
def test_cekajici_indikator_se_nepublikuje(kod):
    metodiky = publikace.nacti_metodiky()
    kod_metodiky = ind.metodika(kod)["kod"]
    assert metodiky[kod_metodiky]["stav"] == "ceka_na_zdroj"
    v = {"druh": "indikator", "indikator_kod": kod, "obdobi_od": "2026-01-01", "obdobi_do": "2026-10-01",
         "pocet_pripadu": 40, "zaklad": 40, "srovnavaci_skupina": "test", "metodika_verze": kod_metodiky,
         "text": "Signál k prověření."}
    assert "INDIKATOR_CEKA_NA_ZDROJ" in {p.kod for p in publikace.over_vystup(v, metodiky, "test")}


def _texty_vzorku() -> list[str]:
    """Texty, které indikátory skutečně generují (vzorová data)."""
    f = [{"zadavatel": "00255513", "cpv": "45000000", "typ": "result", "nabidky": [1] * 6, "zahajeni": date(2026, 9, 1)}]
    texty = [v.text for v in ind.jedina_nabidka(f, {})]
    texty.append(ind.Vysledek("koncentrace_dodavatele", "1", date(2026, 1, 1), date(2026, 2, 1), 5, Decimal(1), Decimal(1),
                              "x", "Signál k prověření: největší dodavatel zadavatele má 100 % objemu").text)
    return texty


@pytest.mark.parametrize("text", _texty_vzorku())
def test_texty_indikatoru_bez_hodnoticich_vyrazu(text):
    assert publikace.over_text(text) == [] and text.startswith("Signál k prověření")


def test_zdrojovy_kod_indikatoru_neobsahuje_zakazane_vyrazy():
    """Všechny textové šablony indikátorů (celý modul) projdou kontrolou hodnotících výrazů."""
    from pathlib import Path

    zdroj = Path(ind.__file__).read_text(encoding="utf-8")
    sablony = [radek for radek in zdroj.splitlines() if "Signál k prověření" in radek or 'f"' in radek]
    assert sablony and all(publikace.over_text(s) == [] for s in sablony)
