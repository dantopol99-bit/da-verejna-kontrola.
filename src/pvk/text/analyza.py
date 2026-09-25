"""Vysvětlitelná analýza textu smlouvy: částky, data, výskyt IČO, značky znečitelnění, periodicita.

Všechny funkce vracejí i důkaz (úryvek textu), aby šel každý verdikt ručně ověřit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

# --- částky --------------------------------------------------------------------------------------

_CISLO_TELO = r"(\d{1,3}(?:[  .]\d{3})+|\d{1,12})(?:,(\d{1,2}|-{1,2}))?"
# číslo nesmí navazovat na číslici, písmeno ani oddělovač: "m3 EUR" není 3 EUR, "Kč/m2 500 Kč" není 2 500 Kč
_CISLO = r"(?<![\w.,])" + _CISLO_TELO
RE_CASTKA_ZA = re.compile(_CISLO + r"\s*(Kč|CZK|korun|Kc|EUR|€|USD)(?![a-zá-ž])", re.I)
RE_CASTKA_PRED = re.compile(r"(Kč|CZK|EUR|€)\s*(?<![\d.,])" + _CISLO_TELO, re.I)
RE_CASTKA_POMLCKA = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ \u00a0.]\d{3})+|\d{1,12}),-(?![\d-])")

KLICOVA_SLOVA_CENY = re.compile(
    r"cen[ayuěo]|hodnot|odměn|úhrad|nájemn|celkem|částk|poplat|platb|fakturov|honorář|paušál|"
    r"dotac|příspěv|kupní|úplat|rozpočet|předpokl|pojistné\b(?!\s+plnění)",
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


# Částka v cenovém kontextu, která přesto není cenou plnění: jednotková sazba (za částkou "/m2",
# "za hodinu", "na osobu"), sankce, úrok z prodlení, práh ("vyšší než"), spoluúčast či limit pojištění,
# jistota, kauce. Rozhoduje věta před částkou (od posledního ".", ";" nebo prázdného řádku).
RE_ZA_JEDNOTKU = re.compile(
    r"^\s*(?:bez\s+DPH\s*|vč\.?\s*DPH\s*|s\s+DPH\s*)?"
    r"(?:/\s*|za\s+(?:každ\w+\s+|jeden\s+|jednu\s+|1\s+)?|na\s+(?:jednu\s+|jednoho\s+)?)"
    r"(?:hod\w*|h\b|ks\b|kus\w*|km\b|m2|m²|m3|m\b|t\b|kg\b|den\b|dny\b|dní\b|osob\w*|MJ\b|stran\w*|měrnou)",
    re.I,
)
RE_NENI_CENA_PLNENI = re.compile(
    r"hodinov\w*\s+sazb|denní\s+sazb|sazb\w*\s+za\s+(?:hodin|den)|pokut|úrok\w*\s+z\s+prodlení|penále|"
    r"spoluúčast|pojistn\w*\s+(?:událost|částk|plnění)|pojištění\s+odpovědnosti|limit\w*\s+pojist|"
    r"jistot|kauc|bankovní\w*\s+záruk|vyšš[ií]\s+než|nižš[ií]\s+než|nad\s+částku|přesahující",
    re.I,
)
# práh bezprostředně před částkou: "(nad 150 000 Kč)", "minimálně 1000,- Kč", "alespoň 5 000 Kč"
RE_PRAH_PRED_CASTKOU = re.compile(r"\b(?:nad|pod|minimáln\w*|alespoň|nejméně)\s*(?:ve\s+výši\s*)?$", re.I)


def je_cena_plneni(text: str, n: NalezCastky) -> bool:
    """Částka v cenovém kontextu, která je cenou plnění (ne jednotková sazba, sankce, práh či jistota)."""
    if not n.cenovy_kontext or RE_ZA_JEDNOTKU.search(text[n.konec: n.konec + 30]):
        return False
    zacatek = max(0, n.zacatek - 200)
    hranice = max(text.rfind(".", zacatek, n.zacatek), text.rfind(";", zacatek, n.zacatek),
                  text.rfind("\n\n", zacatek, n.zacatek))
    veta_pred = text[hranice + 1 if hranice >= 0 else zacatek: n.zacatek]
    return not (RE_NENI_CENA_PLNENI.search(veta_pred) or RE_PRAH_PRED_CASTKOU.search(veta_pred))


def ceny_plneni(text: str, nalezy: list[NalezCastky]) -> list[NalezCastky]:
    return [n for n in nalezy if je_cena_plneni(text, n)]


def castka_v_textu(hodnota: Decimal, nalezy: list[NalezCastky], tolerance_kc: Decimal = Decimal(1)) -> NalezCastky | None:
    """Najde částku rovnou `hodnota` (± tolerance v Kč – zrcadlo zaokrouhluje na celé koruny)."""
    for n in nalezy:
        if abs(n.hodnota - hodnota) <= tolerance_kc:
            return n
    return None


def _vzor_cisla(cele: int) -> str:
    """Celé číslo s volitelnými oddělovači tisíců: 1122106 -> 1[ .]?122[ .]?106."""
    cislice = str(cele)
    skupiny = []
    while cislice:
        skupiny.insert(0, cislice[-3:])
        cislice = cislice[:-3]
    return r"[ \u00a0.']?".join(skupiny)


MIN_HODNOTA_BEZ_MENY = Decimal(1000)  # menší čísla bez měny se v textu shodují náhodou (500 ml, 100 %)


def hodnota_v_textu(hodnota: Decimal, text: str) -> str | None:
    """Cílené hledání známé hodnoty (z metadat) v textu v libovolném běžném zápisu, i bez označení
    měny (tabulky): 99 000,00 / 99.000,- / 70 325.00 / 155.000, - CZK. Hodnota ze zrcadla je
    zaokrouhlená na celé Kč, proto se zkouší i celá část o 1 nižší (…,50–…,99). Vrací úryvek."""
    if hodnota is None or hodnota < MIN_HODNOTA_BEZ_MENY:
        return None
    zaklad = int(hodnota)
    for cele in {zaklad, zaklad - 1} - {0}:
        vzor = r"(?<![\d.,])" + _vzor_cisla(cele) + r"(?:[.,]\s?(?:\d{1,2}|-{1,2}))?(?![\d])"
        m = re.search(vzor, text)
        if m:
            desetinna = re.search(r"[.,]\s?(\d{1,2})$", m.group(0))
            presna = Decimal(cele) + (Decimal(desetinna.group(1)) / 10 ** len(desetinna.group(1)) if desetinna else 0)
            if abs(presna - hodnota) <= 1:
                return uryvek(text, m.start(), m.end())
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
# Datum podpisu: "V <Místo> dne 3. 9. 2026", "Datum podpisu: …", "Digitálně podepsal … Datum: …".
# Odkazy na jiné dokumenty ("usnesením … ze dne", "ode dne", "do dne") datem podpisu nejsou.
_VELKA = "A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ"
_MALA = "a-záčďéěíňóřšťúůýž"
RE_PODPIS_MISTO_DNE = re.compile(
    rf"\bV\s+[{_VELKA}][{_MALA}]*(?:[ -][{_VELKA}{_MALA}]+){{0,3}}\s*,?\s*dne\s*:?\s*$"
)
RE_PODPIS_JINAK = re.compile(r"(?:datum\s+podpisu\s*:?|podepsal\w*\b.{0,60}datum\s*:|podepsáno\s+(?:dne)?\s*:?)\s*$",
                             re.I | re.S)
RE_ODKAZ_NA_JINY_DOKUMENT = re.compile(r"\b(?:ze|ode|od|do)\s+dne\s*:?\s*$", re.I)


def je_kontext_podpisu(pred: str) -> bool:
    """Text bezprostředně před datem (cca 60 znaků) odpovídá místu a datu podpisu."""
    if RE_ODKAZ_NA_JINY_DOKUMENT.search(pred):
        return False
    return bool(RE_PODPIS_MISTO_DNE.search(pred) or RE_PODPIS_JINAK.search(pred))


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
            pred = text[max(0, m.start() - 60): m.start()]
            nalezy.append(NalezData(d, je_kontext_podpisu(pred), uryvek(text, m.start(), m.end(), 50)))
    for m in RE_DATUM_SLOVY.finditer(text):
        d = _datum(m.group(3), MESICE[m.group(2).lower()], m.group(1))
        if d:
            pred = text[max(0, m.start() - 60): m.start()]
            nalezy.append(NalezData(d, je_kontext_podpisu(pred), uryvek(text, m.start(), m.end(), 50)))
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
    if not m:  # artefakty extrakce: IČO přilepené ke štítku ("ıč0263434466" = "IČO: 63434466")
        m = re.search(r"[iıI]\s?[cčČC][^\n\d]{0,3}\d{0,2}" + vzor + r"(?!\d)", text)
    if not m:
        bez_nul = ico.lstrip("0")
        if bez_nul != ico and len(bez_nul) >= 5:
            m = re.search(r"IČ[OZ]?\s*:?\s*" + r"\s?".join(bez_nul) + r"(?!\d)", text)
    return uryvek(text, m.start(), m.end(), 40) if m else None


# --- znečitelnění --------------------------------------------------------------------------------

# Slovní značka ("anonymizováno", "znečitelněno"…) se počítá jen jako zástupný údaj: v závorce, za
# dvojtečkou nebo samostatně na řádku. Ve větě jde obvykle o doložku o uveřejnění ("údaje, které by
# jinak podléhaly znečitelnění"), ne o znečitelněný text.
_SLOVNI_ZNACKA = r"(?:anonymizov[áa]no|znečitelněno|začerněno|redigov[áa]no|skryto|osobní\s+údaj)"
RE_ZNACKY_ZNECITELNENI = re.compile(
    r"(?<![A-Za-z])[Xx]{5,}(?![A-Za-z])|[█■▇▆▅▀▄]{2,}|\*{5,}"
    r"|[\[(]\s*" + _SLOVNI_ZNACKA + r"\s*[\])]"
    r"|:[ \t]*" + _SLOVNI_ZNACKA + r"[ \t]*(?:$|[,;])"
    r"|^[ \t]*" + _SLOVNI_ZNACKA + r"[ \t]*$",
    re.I | re.M,
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


# Doba plnění se bere jen z věty o smlouvě / plnění; záruka, udržitelnost projektu, archivace,
# mlčenlivost ani souhlas se zveřejněním dobou plnění nejsou.
RE_VETA_O_PLNENI = re.compile(
    r"smlouv|nájem|nájm|pacht|služb|plnění|dodáv|servis|podpor|licenc|provoz|údržb|dohod|spolupráce", re.I
)
RE_VETA_JINA_DOBA = re.compile(
    r"záru|udržitel|archiv|uchov|mlčenliv|promlč|zveřejn|souhlas|pojištěn|garanc|reklamac|lhůt", re.I
)
MAX_DELKA_DNI = 50 * 365
# průběžně poskytované plnění (služby, nájem, licence…) – na rozdíl od jednorázového díla nebo dodávky
RE_PRUBEZNE_PLNENI = re.compile(
    r"služb|servis|údržb|provoz|podpor|nájem|nájm|pronáj|pacht|licenc|poskytován|předplat", re.I
)


def _veta(text: str, zacatek: int, konec: int) -> str:
    """Věta kolem nálezu (ohraničená tečkou, středníkem nebo prázdným řádkem, nejvýš 300 znaků)."""
    levy = max(text.rfind(".", max(0, zacatek - 300), zacatek), text.rfind(";", max(0, zacatek - 300), zacatek),
               text.rfind("\n\n", max(0, zacatek - 300), zacatek))
    pravy_kandidati = [i for i in (text.find(".", konec, konec + 300), text.find(";", konec, konec + 300)) if i >= 0]
    pravy = min(pravy_kandidati) if pravy_kandidati else min(len(text), konec + 300)
    return text[levy + 1 if levy >= 0 else max(0, zacatek - 300): pravy]


def _doba_plneni_vetou(text: str, m: re.Match) -> bool:
    veta = _veta(text, m.start(), m.end())
    return bool(RE_VETA_O_PLNENI.search(veta)) and not RE_VETA_JINA_DOBA.search(veta)


def doba_plneni(text: str) -> dict:
    """Signály doby plnění: neurčitá, určitá s délkou (dny), rozsah od–do – jen z vět o plnění."""
    vysledek: dict = {"neurcita": None, "delka_dni": None, "prubezne": False, "dukaz": []}
    for m in RE_NEURCITA.finditer(text):
        if "souhlas" in m.group(0).lower():
            continue
        vysledek["neurcita"] = True
        vysledek["dukaz"].append(uryvek(text, m.start(), m.end(), 60))
        break
    for m in RE_PO_DOBU.finditer(text):
        if not _doba_plneni_vetou(text, m):
            continue
        n = _pocet(m.group(1))
        jednotka = m.group(2).lower()
        dni = n * 365 if jednotka.startswith(("let", "rok")) else n * 30
        if dni and dni <= MAX_DELKA_DNI and (vysledek["delka_dni"] is None or dni > vysledek["delka_dni"]):
            vysledek["delka_dni"] = dni
            vysledek["prubezne"] = bool(RE_PRUBEZNE_PLNENI.search(_veta(text, m.start(), m.end())))
            vysledek["dukaz"].append(uryvek(text, m.start(), m.end(), 60))
    for m in RE_OD_DO.finditer(text):
        if not _doba_plneni_vetou(text, m):
            continue
        od = RE_DATUM_CISLA.search(m.group(1))
        do = RE_DATUM_CISLA.search(m.group(2))
        if od and do:
            d1, d2 = _datum(od.group(3), od.group(2), od.group(1)), _datum(do.group(3), do.group(2), do.group(1))
            if d1 and d2 and d2 > d1:
                dni = (d2 - d1).days
                if dni <= MAX_DELKA_DNI and (vysledek["delka_dni"] is None or dni > vysledek["delka_dni"]):
                    vysledek["delka_dni"] = dni
                    vysledek["prubezne"] = bool(RE_PRUBEZNE_PLNENI.search(_veta(text, m.start(), m.end())))
                    vysledek["dukaz"].append(uryvek(text, m.start(), m.end(), 40))
    if vysledek["neurcita"] is None and RE_URCITA.search(text):
        vysledek["neurcita"] = False
    return vysledek


MIN_PERIODICKA_CASTKA = Decimal(500)  # menší "periodické" částky jsou v RS jednotkové ceny či poplatky za kus
RE_JEDNOTKA_ZA_CASTKOU = re.compile(r"^\s*(?:bez\s+DPH\s*|vč\.?\s*DPH\s*)?/\s*(?:m2|m²|m3|hod|h\b|ks|km|t\b|kg|den|osob|MJ)", re.I)


def periodicke_castky(text: str, nalezy: list[NalezCastky], okno: int = 80) -> dict[str, list[NalezCastky]]:
    """Částky, u kterých je do `okno` znaků uvedena perioda (roční / měsíční / čtvrtletní)."""
    vysledek: dict[str, list[NalezCastky]] = {"rocni": [], "mesicni": [], "ctvrtletni": []}
    for n in nalezy:
        if n.hodnota < MIN_PERIODICKA_CASTKA or RE_JEDNOTKA_ZA_CASTKOU.search(text[n.konec: n.konec + 25]):
            continue  # jednotková cena (Kč/m², Kč/hod…) nebo drobný poplatek, ne hodnota plnění
        okoli = text[max(0, n.zacatek - okno): n.konec + okno]
        if RE_ROCNE.search(okoli):
            vysledek["rocni"].append(n)
        elif RE_MESICNE.search(okoli):
            vysledek["mesicni"].append(n)
        elif RE_CTVRTLETNE.search(okoli):
            vysledek["ctvrtletni"].append(n)
    return vysledek
