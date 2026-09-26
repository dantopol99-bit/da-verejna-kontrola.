"""Párování smlouva (registr smluv) – zakázka (VVZ) podle metodiky `metodika/parovani-2026.09.json` (D-045).

Doložená shoda (skóre 1, D-006):
  * `odkaz_bt151` – URL smlouvy ve formuláři eForms (BT-151) odkazuje na záznam registru smluv,
  * `ev_cislo_v_rs` – evidenční číslo zakázky (Z…) nebo identifikátor NIPEZ je v metadatech či textu smlouvy
    a IČO zadavatele je mezi stranami smlouvy.
Pravděpodobná shoda (jen při shodě IČO zadavatele i dodavatele se stranami smlouvy):
  skóre = váha IČO + váha data × shoda data + váha částky × shoda částky + váha předmětu × shoda předmětu,
  shora omezené max_skore (nikdy 1); pod prahem shoda není. Každá shoda nese metodu, skóre a zdůvodnění.
Propojení zakázka – smlouva je případ se stavem shody, nikdy tok (D-026).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from pvk.config import KOREN
from pvk.zdroje.rs import ZaznamRS
from pvk.zdroje.vvz import OznameniVVZ

METODIKA = KOREN / "metodika" / "parovani-2026.09.json"
RE_EV_CISLO = re.compile(r"\bZ\d{4}-\d{6}\b")
RE_NIPEZ = re.compile(r"\bN\d{3}/\d{2}/V\d{8}\b")


def parametry(cesta: Path = METODIKA) -> dict:
    return json.loads(cesta.read_text(encoding="utf-8"))["parametry"]


@dataclass
class ZakazkaP:
    """Zakázka (nebo její část / uzavřená smlouva z oznámení o výsledku) připravená k párování."""

    tok_klic: str
    ev_cislo: str | None
    ico_zadavatelu: set[str]
    ico_dodavatelu: set[str]
    datum_uzavreni: date | None
    cena_bez_dph: Decimal | None  # vysoutěžená cena v CZK bez DPH
    predmet: str | None = None
    nipez: str | None = None
    odkazy_rs: set[str] = field(default_factory=set)  # ID verzí RS z BT-151


@dataclass
class Shoda:
    tok_klic: str
    id_verze: str
    stav: str  # dolozena | pravdepodobna
    skore: float
    metoda: str
    zduvodneni: str


def zakazky_z_oznameni(ozn: OznameniVVZ) -> list[ZakazkaP]:
    """Uzavřené smlouvy z oznámení o výsledku VVZ (parsuj_eforms) jako zakázky k párování."""
    zadavatele = {z.ico for z in ozn.zadavatele if z.ico}
    return [
        ZakazkaP(
            tok_klic=f"vvz:{ozn.ev_cislo_zakazky}" + (f":{','.join(s.casti)}" if s.casti else ""),
            ev_cislo=ozn.ev_cislo_zakazky,
            ico_zadavatelu=zadavatele,
            ico_dodavatelu={d.ico for d in s.dodavatele if d.ico},
            datum_uzavreni=s.datum_uzavreni,
            cena_bez_dph=s.hodnota if (s.mena or "CZK") == "CZK" else None,
            predmet=ozn.nazev,
            odkazy_rs=set(s.id_verzi_rs),
        )
        for s in ozn.smlouvy
    ]


def _slova(text: str | None) -> set[str]:
    bez = unicodedata.normalize("NFKD", (text or "").lower())
    bez = "".join(ch for ch in bez if not unicodedata.combining(ch))
    return {w for w in re.findall(r"[a-z0-9]+", bez) if len(w) >= 4}


def shoda_predmetu(a: str | None, b: str | None, p: dict) -> float:
    """Jaccardova podobnost slov (≥ 4 znaky, bez diakritiky); plná shoda od `predmet_plna_shoda`."""
    sa, sb = _slova(a), _slova(b)
    if not sa or not sb:
        return 0.0
    return min(1.0, (len(sa & sb) / len(sa | sb)) / float(p["predmet_plna_shoda"]))


def shoda_data(zak: ZakazkaP, sml: ZaznamRS, p: dict) -> float:
    """1 při stejném dni, lineárně k 0 na hranici okna ± okno_dni (datum uzavření BT-145 vs. RS)."""
    if zak.datum_uzavreni is None or sml.datum_uzavreni is None:
        return 0.0
    rozdil = abs((sml.datum_uzavreni - zak.datum_uzavreni).days)
    return max(0.0, 1 - rozdil / int(p["okno_dni"]))


def shoda_castky(zak: ZakazkaP, sml: ZaznamRS, p: dict) -> tuple[float, str | None]:
    """Relativní shoda vysoutěžené ceny (bez DPH) s hodnotou smlouvy; hodnota s DPH se přepočte sazbami DPH."""
    if not zak.cena_bez_dph or zak.cena_bez_dph <= 0:
        return 0.0, None
    tolerance = Decimal(str(p["tolerance_castky"]))
    varianty = [(sml.hodnota_bez_dph, "bez_dph")] if sml.hodnota_bez_dph else []
    if sml.hodnota_vcetne_dph:
        varianty += [(sml.hodnota_vcetne_dph / (1 + Decimal(str(s))), f"s_dph/{1 + s:.2f}") for s in p["sazby_dph"]]
    nejlepsi, zpusob = Decimal(0), None
    for hodnota, jak in varianty:
        shoda = max(Decimal(0), 1 - (abs(hodnota - zak.cena_bez_dph) / zak.cena_bez_dph) / tolerance)
        if shoda > nejlepsi:
            nejlepsi, zpusob = shoda, jak
    return float(nejlepsi), zpusob


def ica_smlouvy(sml: ZaznamRS) -> set[str]:
    ica = {s.ico for s in sml.smluvni_strany if s.ico}
    if sml.subjekt and sml.subjekt.ico:
        ica.add(sml.subjekt.ico)
    return ica


def paruj_jednu(zak: ZakazkaP, sml: ZaznamRS, p: dict, text_smlouvy: str = "") -> Shoda | None:
    ica = ica_smlouvy(sml)
    if sml.id_verze in zak.odkazy_rs:
        return Shoda(zak.tok_klic, sml.id_verze, "dolozena", 1.0, "odkaz_bt151",
                     "URL smlouvy ve formuláři VVZ (BT-151) odkazuje na tento záznam registru smluv")
    metadata = " ".join(filter(None, [sml.predmet, sml.cislo_smlouvy, text_smlouvy]))
    identifikatory = set(RE_EV_CISLO.findall(metadata)) | set(RE_NIPEZ.findall(metadata))
    if zak.ico_zadavatelu & ica and ({zak.ev_cislo, zak.nipez} - {None}) & identifikatory:
        return Shoda(zak.tok_klic, sml.id_verze, "dolozena", 1.0, "ev_cislo_v_rs",
                     "evidenční číslo / identifikátor NIPEZ zakázky je ve smlouvě a IČO zadavatele souhlasí")
    if not (zak.ico_zadavatelu & ica and zak.ico_dodavatelu & ica):
        return None
    v = p["vahy"]
    s_datum = shoda_data(zak, sml, p)
    s_castka, zpusob = shoda_castky(zak, sml, p)
    s_predmet = shoda_predmetu(zak.predmet, sml.predmet, p)
    skore = v["ico"] + v["datum"] * s_datum + v["castka"] * s_castka + v["predmet"] * s_predmet
    skore = round(min(skore, float(p["max_skore"])), 3)
    if skore < float(p["prah_pravdepodobne"]):
        return None
    return Shoda(zak.tok_klic, sml.id_verze, "pravdepodobna", skore, "heuristika_ico_datum_castka_predmet",
                 f"IČO zadavatele i dodavatele; datum {s_datum:.2f}, částka {s_castka:.2f} ({zpusob or '–'}), "
                 f"předmět {s_predmet:.2f}")


def paruj(zakazky: list[ZakazkaP], smlouvy: list[ZaznamRS], p: dict | None = None,
          texty: dict[str, str] | None = None) -> list[Shoda]:
    """Všechny shody zakázek se smlouvami; ke každé zakázce doložené shody, jinak nejlepší pravděpodobná."""
    p = p or parametry()
    vysledek = []
    for zak in zakazky:
        shody = [s for sml in smlouvy if (s := paruj_jednu(zak, sml, p, (texty or {}).get(sml.id_verze, "")))]
        dolozene = [s for s in shody if s.stav == "dolozena"]
        if dolozene:
            vysledek += dolozene
        elif shody:
            vysledek.append(max(shody, key=lambda s: (s.skore, s.id_verze)))
    return vysledek
