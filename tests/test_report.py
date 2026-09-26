"""Report pilotu ze syntetických mezivýsledků: vznikne, obsahuje čtyři čísla a projde publikační bránou."""

import csv
import json
from datetime import UTC, date, datetime

from pvk import publikace
from pvk.core import zajisti_metodiku
from pvk.pilot import report
from pvk.pilot.kontext import Kontext
from pvk.pilot.statistika import Podil

METODIKA = json.loads((publikace.KOREN / "metodika" / "pilot-2026.09.json").read_text(encoding="utf-8"))


def _p(c, n):
    return Podil(c, n).jako_dict()


def _vysledky():
    polozka_p1 = {
        "id_verze": "39673953", "odkaz": "https://smlouvy.gov.cz/smlouva/39673953", "cas_zverejneni": "2026-08-25",
        "datum_uzavreni": "2026-08-24", "ico_subjektu": True, "ico_protistrany": True, "protistran_bez_ico": 0,
        "castka_v_metadatech": True, "hodnota_bez_dph": "100", "hodnota_vcetne_dph": None, "cizi_mena": None,
        "duvod_neuvedeni_ceny": False, "m1_ico_obe_strany_a_castka": True, "prilohy": [{"stav": "zpracovano"}],
        "text_citelny": True, "castka_v_priloze": True, "m2_castka_jen_v_priloze": False, "m3_znecitelneno": True,
        "znecitelneni": ["textové značky"], "kontroly": {"castka": "shoda", "datum_uzavreni": "shoda", "ico": {}},
    }
    p1 = {
        "zdroj": "hlidac", "info_zdroje": {}, "n": 200,
        "vyber": {"metoda": "skupiny_id_zrcadlo", "hranice_id": [1, 2], "skupin": 300, "dotazu": 330,
                  "prazdna_skupina": 90, "neplatna_verze": 5, "mimo_obdobi": 5, "chyba_stazeni": 0},
        "m1_ico_obe_strany_a_castka": _p(170, 200), "m2_castka_jen_v_priloze": _p(12, 200), "m3_znecitelneno": _p(60, 200),
        "rozpad": {k: _p(150, 200) for k in ("ico_subjektu", "ico_protistrany", "castka_v_metadatech",
                                              "duvod_neuvedeni_ceny", "text_citelny", "m2_mezi_bez_castky",
                                              "m3_mezi_citelnymi")},
        "polozky": [polozka_p1],
        "vyjimky": [{"zaznam": "39673953", "udaj": "castka", "hodnota_metadata": "bez DPH 100,00 Kč",
                     "nalezeno_v_textu": "250,00 Kč (kontext: cena)", "odkaz_zaznamu": "https://smlouvy.gov.cz/smlouva/39673953",
                     "odkaz_originalu": "", "navrh_verdiktu": "NESHODA – ověřit", "zduvodneni": "test"}],
    }
    p2 = {
        "meta": {"ramec": 35786, "losovano_pozic": 60, "odmitnuto": {"bez_uzavrene_smlouvy": 10}},
        "n": 50, "pocty": {"dolozene": 20, "jen_heuristicky": 15, "nesparovano": 15},
        "dolozene": _p(20, 50), "jen_heuristicky": _p(15, 50), "sparovano_celkem": _p(35, 50),
        "validace_heuristiky": {"dolozenych_zakazek": 20, "heuristika_nasla_dolozenou": 15, "dolozena_je_nejlepsi": 14,
                                "heuristika_nasla_neco": 16},
        "polozky": [{"ev_cislo_formulare": "F1", "ev_cislo_zakazky": "Z1", "odkaz": "x", "druh_formulare": "29",
                     "datum_uverejneni": "2026-01-01", "zdroj_podani": "WEB", "zadavatele_ico": ["00255513"],
                     "pocet_smluv": 1, "kategorie": "jen_heuristicky", "dolozene": [],
                     "heuristika": [{"nejlepsi": {"id_verze": "1", "skore": 0.9, "shoda_data": 1, "shoda_castky": 0.8},
                                     "kandidati": [{}]}]}],
    }
    p3 = {"n_opakovane": 40, "n_p1": 200, "bez_citelneho_textu": 10, "pocty": {"ano": 10, "ne": 20, "nejasne": 10},
          "ano": _p(10, 40), "ne": _p(20, 40), "nejasne": _p(10, 40),
          "polozky": [{"id_verze": "1", "odkaz": "x", "neurcita": True, "delka_dni": None, "periodicke": {"mesicni": ["10"]},
                       "verdikt": "ano", "rocni_hodnota": "120", "duvod": "jednoznačná mesicni částka"}],
          "vyjimky": []}
    p4 = {
        "red": {"stav": "zmereno", "n": 200, "meta": {"ramec": 14008, "okno_od": "2024-12-17", "okno_do": "2025-12-17",
                                                      "posledni_podpis_v_datech": "2025-12-16"},
                "slozeni_ramce": {"fo_bez_ico": 12930, "fo_s_ico": 120, "po_s_ico": 958, "po_bez_ico": 0},
                "ramec_v_rozsahu": 1078, "podil_fo_bez_ico_v_ramci": _p(12930, 14008),
                "kategorie": {"ico_ares_shoda_nazvu": 199, "ico_ares_jiny_nazev": 1},
                "sparovatelne": _p(199, 200), "sparovatelne_vcetne_jineho_nazvu": _p(200, 200),
                "polozky": [{"id_ve_zdroji": "FO", "pravni_forma": "101", "je_fyzicka_osoba": True, "ico": "12345678",
                             "kategorie": "ico_ares_shoda_nazvu", "podobnost_nazvu": None}]},
        "szif": {"stav": "nedostupne", "duvod": "server vrací JavaScriptovou anti-bot výzvu"},
    }
    dostupnost = [{"zdroj": "registr_smluv", "url": "https://data.smlouvy.gov.cz/index.xml", "popis": "RS",
                   "cas": datetime.now(UTC).isoformat(), "http_status": None, "chyba": "ConnectionError", "stav": "nedostupne"}]
    return {"p1": p1, "p2": p2, "p3": p3, "p4": p4, "dostupnost": dostupnost}


def test_report_ze_syntetickych_vysledku(db, tmp_path):
    metodika_id = zajisti_metodiku(db, METODIKA)
    db.commit()
    adresar = tmp_path / "pilot"
    adresar.mkdir()
    for jmeno, data in _vysledky().items():
        (adresar / f"{jmeno}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ctx = Kontext(conn=db, nast=None, stahovac=None, metodika=METODIKA["parametry"], metodika_id=str(metodika_id),
                  seed=1, od=date(2025, 9, 1), do=date(2026, 9, 1), adresar_vysledku=adresar)
    docs = tmp_path / "docs"
    cesta = report.vytvor(ctx, docs=docs)
    text = cesta.read_text(encoding="utf-8")
    for kus in ("## Shrnutí – čtyři čísla", "| P1 |", "| P2 |", "| P3 |", "| P4 |", "(a) Toky", "(b) Indikátor"):
        assert kus in text
    # rozhodnutí po pilotu (D-026–D-030) místo doporučení; SZIF se nevyhodnocuje (D-028)
    for kus in ("D-026 (D1)", "D-027 (D2)", "D-028 (D3)", "D-029 (D4)", "D-030 (D5)", "## 5. Rozhodnutí po pilotu"):
        assert kus in text
    assert "P4 spárovatelnost – SZIF" not in text
    assert publikace.over_text(text) == []
    # D-031: ručně jen neshody, částka jen v příloze a jiné IČO; „nelze ověřit“ a „nejasné“ jako kategorie
    with (docs / "pilot_vyjimky.csv").open(encoding="utf-8") as f:
        rucne = list(csv.DictReader(f))
    with (docs / "pilot_vyjimky_kategorie.csv").open(encoding="utf-8") as f:
        kategorie = list(csv.DictReader(f))
    assert sorted(r["id"] for r in rucne + kategorie)[0] == "V001"
    assert all(r["potvrzeno"] == "" and not r["navrh_verdiktu"].startswith(("NELZE", "NEJASNÉ")) for r in rucne)
    assert all(r["potvrzeno"].startswith("přijato automaticky") for r in kategorie)
    # FO: IČO podnikající fyzické osoby se v datech P4 nezobrazuje
    with (docs / "pilot_data" / "p4_vzorek.csv").open(encoding="utf-8") as f:
        assert all(r["ico"] == "" for r in csv.DictReader(f) if r["je_fyzicka_osoba"] == "True")
    # výsledky měření se zapsaly do ind a projdou minimálním základem
    kody = {r["indikator_kod"] for r in db.execute(
        "SELECT indikator_kod FROM ind.indikator_k_publikaci WHERE metodika_verze_id = %s", (metodika_id,))}
    assert {"pilot_p1_ico_obe_strany_a_castka", "pilot_p2_dolozene", "pilot_p4_sparovatelne_red"} <= kody
