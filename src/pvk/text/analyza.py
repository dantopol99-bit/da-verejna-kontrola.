"""Vysvětlitelná analýza textu smlouvy: částky, data, výskyt IČO, značky znečitelnění, periodicita.

Všechny funkce vracejí i důkaz (úryvek textu), aby šel každý verdikt ručně ověřit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

# --- částky --------------------------------------------------------------------------------------

_CISLO = r"(?<![\d.,])(\d{1,3}(?:[  .]\d{3})+|\d{1,12})(?:,(\d{1,2}|-{1,2}))?"
RE_CASTKA_ZA = re.compile(_CISLO + r"\s*(Kč|CZK|korun|Kc|EUR|€|USD)(?![a-zá-ž])", re.I)
RE_CASTKA_PRED = re.compile(r"(Kč|CZK|EUR|€)\s*" + _CISLO, re.I)
RE_CASTKA_POMLCKA = re.compile(r"(?<![\d.,])(\d{1,3}(?:[ \u00a0.]\d{3})+|\d{1,12}),-(?![\d-])")

KLICOVA_SLOVA_CENY = re.compile(
    r"cen[ayuěo]|hodnot|odměn|úhrad|nájemn|celkem|částk|poplat|platb|fakturov|honorář|paušál|"
    r"dotac|příspěv|kupní|úplat|rozpočet|předpokl",
    re.I,
)
MENY = {"kč": "CZK", "czk": "CZK", "korun": "CZK", "kc": "CZK", "eur": "EUR", "€": "EUR", "usd": "USD"}


@dataclass(frozen=True)
class NalezCastky:
    hodnota: Decimal
    mena: str
    zacatek: int
    konec: int
    cenovy_kontext: bool
    uryvek: str
    klicove_slovo: str | None = None


def _na_decimal(cela: str, desetinna: str | None) -> Decimal | None:
    cela = cela.replace(" ", "").replace(" ", "").replace(".", "")
    try:
        hodnota = Decimal(cela)
    except InvalidOperation:
        return None
    if desetinna and desetinna.isdigit():
        hodnota += Decimal(desetinna) / (10 ** len(desetinna))
    return hodnota


def uryvek(text: str, zacatek: int, konec: int, okno: int = 80) -> str:
    return re.sub(r"\s+", " ", text[max(0, zacatek - okno): konec + okno]).strip()


def najdi_castky(text: str, okno_kontextu: int = 160) -> list[NalezCastky]:
    nalezy: dict[tuple[int, int], NalezCastky] = {}
    for vzor, poradi in ((RE_CASTKA_ZA, "za"), (RE_CASTKA_PRED, "pred"), (RE_CASTKA_POMLCKA, "pomlcka")):
        for m in vzor.finditer(text):
            if poradi == "za":
                hodnota, mena = _na_decimal(m.group(1), m.group(2)), MENY.get(m.group(3).lower(), "CZK")
            elif poradi == "pred":
                hodnota, mena = _na_decimal(m.group(2), m.group(3)), MENY.get(m.group(1).lower(), "CZK")
            else:
                hodnota, mena = _na_decimal(m.group(1), None), "CZK"
            if hodnota is None or hodnota <= 0:
                continue
            if any(z <= m.start() < k or z < m.end() <= k for z, k in nalezy):
                continue
            kontext = text[max(0, m.start() - okno_kontextu): m.end() + 40]
            klic = KLICOVA_SLOVA_CENY.search(kontext)
            nalezy[(m.start(), m.end())] = NalezCastky(
                hodnota, mena, m.start(), m.end(), bool(klic), uryvek(text, m.start(), m.end()),
                klic.group(0).lower() if klic else None,
            )
    return sorted(nalezy.values(), key=lambda n: n.zacatek)


def castka_v_textu(hodnota: Decimal, nalezy: list[NalezCastky], tolerance_kc: Decimal = Decimal(1)) -> NalezCastky | None:
    """Najde částku rovnou `hodnota` (± tolerance v Kč – zrcadlo zaokrouhluje na celé koruny)."""
    for n in nalezy:
        if abs(n.hodnota - hodnota) <= tolerance_kc:
            return n
    return None


# --- data ----------------------------------------------------------------------------------------

MESICE = {
    "ledna": 1, "února": 2, "unora": 2, "března": 3, "brezna": 3, "dubna": 4, "května": 5, "kvetna": 5,
    "června": 6, "cervna": 6, "července": 7, "cervence": 7, "srpna": 8, "září": 9, "zari": 9,
    "října": 10, "rijna": 10, "listopadu": 11, "prosince": 12,
}
RE_DATUM_CISLA = re.compile(r"(?<!\d)(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})(?!\d)")
RE_DATUM_SLOVY = re.compile(r"(?<!\d)(\d{1,2})\.\s?(" + "|".join(MESICE) + r")\s+(\d{4})(?!\d)", re.I)
RE_DATUM_ISO_PODPIS = re.compile(r"(?<!\d)(\d{4})[.-](\d{2})[.-](\d{2})[ T]\d{2}:\d{2}")
RE_KONTEXT_PODPISU = re.compile(r"\bdne\b|podeps|podpis|datum:", re.I)


@dataclass(frozen=True)
class NalezData:
    datum: date
    podpis: bool
    uryvek: str


def najdi_data(text: str) -> list[NalezData]:
    nalezy = []
    for m in RE_DATUM_CISLA.finditer(text):
        d = _datum(m.group(3), m.group(2), m.group(1))
        if d:
            kontext = text[max(0, m.start() - 40): m.start()]
            nalezy.append(NalezData(d, bool(RE_KONTEXT_PODPISU.search(kontext)), uryvek(text, m.start(), m.end(), 50)))
    for m in RE_DATUM_SLOVY.finditer(text):
        d = _datum(m.group(3), MESICE[m.group(2).lower()], m.group(1))
        if d:
            kontext = text[max(0, m.start() - 40): m.start()]
            nalezy.append(NalezData(d, bool(RE_KONTEXT_PODPISU.search(kontext)), uryvek(text, m.start(), m.end(), 50)))
    for m in RE_DATUM_ISO_PODPIS.finditer(text):  # razítko elektronického podpisu "Datum: 2026.09.24 10:23"
        d = _datum(m.group(1), m.group(2), m.group(3))
        if d:
            nalezy.append(NalezData(d, True, uryvek(text, m.start(), m.end(), 50)))
    return nalezy


def _datum(rok, mesic, den) -> date | None:
    try:
        d = date(int(rok), int(mesic), int(den))
    except ValueError:
        return None
    return d if 1990 <= d.year <= 2100 else None


# --- IČO -----------------------------------------------------------------------------------------


def ico_v_textu(ico: str, text: str) -> str | None:
    """Výskyt IČO v textu (i s mezerami mezi číslicemi, i bez úvodních nul za „IČ“). Vrací úryvek."""
    vzor = r"\s?".join(ico)
    m = re.search(r"(?<!\d)" + vzor + r"(?!\d)", text)
    if not m:
        bez_nul = ico.lstrip("0")
        if bez_nul != ico and len(bez_nul) >= 5:
            m = re.search(r"IČ[OZ]?\s*:?\s*" + r"\s?".join(bez_nul) + r"(?!\d)", text)
    return uryvek(text, m.start(), m.end(), 40) if m else None


# --- znečitelnění --------------------------------------------------------------------------------

RE_ZNACKY_ZNECITELNENI = re.compile(
    r"(?<![A-Za-z])[Xx]{5,}(?![A-Za-z])|[█■▇▆▅▀▄]{2,}|\*{5,}|\banonymizov[áa]n|\bznečitelněn|\bzačerněn|"
    r"\bredigov[áa]n|\[\s*(?:osobní údaj|skryto|anonymizováno)\s*\]",
    re.I,
)
RE_NAZEV_ZNECITELNENI = re.compile(r"anonym|redig|zne[cč]itel|za[cč]ern|scrub", re.I)


def znacky_znecitelneni(text: str, max_nalezu: int = 3) -> list[str]:
    return [uryvek(text, m.start(), m.end(), 30) for m in list(RE_ZNACKY_ZNECITELNENI.finditer(text))[:max_nalezu]]


# --- periodicita a doba plnění (P3) ---------------------------------------------------------------

# "na dobu neurčitou" se počítá jen ve větě o smlouvě / nájmu (ne např. u souhlasu se zveřejněním)
_SMLUVNI_SLOVA = r"(?:smlouv\w*|nájem\w*|nájm\w*|pacht\w*|dohod\w*|uzavír\w*|uzavřen\w*|objednáv\w*)"
RE_NEURCITA = re.compile(_SMLUVNI_SLOVA + r"[^.;]{0,100}?na\s+dobu\s+neurčit", re.I)
RE_URCITA = re.compile(_SMLUVNI_SLOVA + r"[^.;]{0,100}?na\s+dobu\s+určit", re.I)
RE_PO_DOBU = re.compile(
    r"(?:po\s+dobu|na\s+dobu|na\s+období)\s+(\d{1,3}|jednoho|dvou|tří|čtyř|pěti|šesti|sedmi|osmi|devíti|deseti)\s+"
    r"(let|roků|roky|rok|měsíců|měsíce|měsíc)",
    re.I,
)
SLOVNI_CISLA = {"jednoho": 1, "dvou": 2, "tří": 3, "čtyř": 4, "pěti": 5, "šesti": 6, "sedmi": 7, "osmi": 8,
                "devíti": 9, "deseti": 10}
RE_ROCNE = re.compile(r"ročně|za\s+(?:každý\s+|jeden\s+|kalendářní\s+)?rok\b|roční|p\.\s?a\.|za\s+12\s+měsíc", re.I)
RE_MESICNE = re.compile(r"měsíčně|za\s+(?:každý\s+|jeden\s+|kalendářní\s+)?měsíc\b|měsíční", re.I)
RE_CTVRTLETNE = re.compile(r"čtvrtletně|za\s+(?:každé\s+)?čtvrtletí|čtvrtletní", re.I)
RE_JEDNOTKOVA = re.compile(r"(?:Kč|CZK)\s*(?:bez\s+DPH\s*)?/\s*(?:hod|h\b|ks|km|m2|m²|m3|t\b|kg|den|osob)", re.I)
RE_CELKEM_ZA_DOBU = re.compile(
    r"(?:celkov\w+\s+cen\w+|cena\s+celkem|celková\s+hodnota)[^.]{0,80}(?:za\s+celou\s+dobu|za\s+dobu\s+trvání)", re.I
)
RE_OD_DO = re.compile(
    r"od\s+(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})\s+do\s+(\d{1,2}\.\s?\d{1,2}\.\s?\d{4})", re.I
)
RE_OPAKOVANE_PLNENI = re.compile(
    r"nájemn|nájm|podnájm|pacht|předplatn|paušál|pravideln\w+\s+(?:servis|údržb|dodáv)|opakovan\w+\s+plnění", re.I
)


def _pocet(text: str) -> int:
    return int(text) if text.isdigit() else SLOVNI_CISLA.get(text.lower(), 0)


def doba_plneni(text: str) -> dict:
    """Signály doby plnění: neurčitá, určitá s délkou (dny), rozsah od–do."""
    vysledek: dict = {"neurcita": None, "delka_dni": None, "dukaz": []}
    for m in RE_NEURCITA.finditer(text):
        if "souhlas" in m.group(0).lower():
            continue
        vysledek["neurcita"] = True
        vysledek["dukaz"].append(uryvek(text, m.start(), m.end(), 60))
        break
    for m in RE_PO_DOBU.finditer(text):
        n = _pocet(m.group(1))
        jednotka = m.group(2).lower()
        dni = n * 365 if jednotka.startswith(("let", "rok")) else n * 30
        if dni and (vysledek["delka_dni"] is None or dni > vysledek["delka_dni"]):
            vysledek["delka_dni"] = dni
            vysledek["dukaz"].append(uryvek(text, m.start(), m.end(), 60))
    for m in RE_OD_DO.finditer(text):
        od = RE_DATUM_CISLA.search(m.group(1))
        do = RE_DATUM_CISLA.search(m.group(2))
        if od and do:
            d1, d2 = _datum(od.group(3), od.group(2), od.group(1)), _datum(do.group(3), do.group(2), do.group(1))
            if d1 and d2 and d2 > d1:
                dni = (d2 - d1).days
                if vysledek["delka_dni"] is None or dni > vysledek["delka_dni"]:
                    vysledek["delka_dni"] = dni
                    vysledek["dukaz"].append(uryvek(text, m.start(), m.end(), 40))
    if vysledek["neurcita"] is None and RE_URCITA.search(text):
        vysledek["neurcita"] = False
    return vysledek


def periodicke_castky(text: str, nalezy: list[NalezCastky], okno: int = 80) -> dict[str, list[NalezCastky]]:
    """Částky, u kterých je do `okno` znaků uvedena perioda (roční / měsíční / čtvrtletní)."""
    vysledek: dict[str, list[NalezCastky]] = {"rocni": [], "mesicni": [], "ctvrtletni": []}
    for n in nalezy:
        okoli = text[max(0, n.zacatek - okno): n.konec + okno]
        if RE_ROCNE.search(okoli):
            vysledek["rocni"].append(n)
        elif RE_MESICNE.search(okoli):
            vysledek["mesicni"].append(n)
        elif RE_CTVRTLETNE.search(okoli):
            vysledek["ctvrtletni"].append(n)
    return vysledek
