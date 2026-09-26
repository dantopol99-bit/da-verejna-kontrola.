"""Zrcadlo registru smluv na Hlídači státu (www.hlidacstatu.cz).

Používá se, jen když oficiální otevřená data registru smluv nejsou dostupná (viz D-013). Čteme
veřejné stránky detailu smlouvy (/Detail/{idVerze}), vyhledávání (/HledatSmlouvy) a kopie příloh
(/KopiePrilohy/{idVerze}?hash=...). Kopie přílohy se přijme jen tehdy, když její SHA-256 souhlasí
s hashem přílohy z metadat registru smluv – tedy jde bajtově o tentýž soubor jako originál.

Ze stránky se nepřebírají žádné údaje Hlídače státu nad rámec registru smluv (K-Index,
„angažovanost politicky aktivních osob“, sponzoring apod. se ignorují – pravidla 5 a 6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from lxml import html as lxml_html

from pvk.http import Odpoved, Stahovac
from pvk.zdroje.rs import PrilohaRS, StranaRS, ZaznamRS, na_decimal, odkaz_rs, strana

HS_URL = "https://www.hlidacstatu.cz"
ZDROJ = "hlidac_statu_rs"
PRAHA = ZoneInfo("Europe/Prague")

_MESICE_CISLA = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.text_content()).strip() if el is not None else ""


def _datum(text: str | None) -> date | None:
    if not text:
        return None
    m = _MESICE_CISLA.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _parsuj_strany(td) -> list[StranaRS]:
    if td is None:
        return []
    strany = []
    for p in td.xpath("./p"):
        text = _text(p)
        if not text:
            continue
        b = p.xpath(".//b")
        nazev = _text(b[0]) if b else None
        ico = re.search(r"\bICO\s*:?\s*(\d{1,8})\b", text)
        ds = re.search(r"dat\.\s*schránka\s+([a-z0-9]{7})\b", text)
        strany.append(
            strana(
                nazev,
                ico.group(1) if ico else None,
                datova_schranka=ds.group(1) if ds else None,
                platce=True if "Plátce peněz" in text else None,
                prijemce=True if "Příjemce peněz" in text else None,
            )
        )
    return strany


def _stejna_strana(a: StranaRS, b: StranaRS) -> bool:
    if a.ico and b.ico:
        return a.ico == b.ico
    return bool(a.nazev and b.nazev and a.nazev.strip().lower() == b.nazev.strip().lower())


def parsuj_detail(obsah: str, id_verze: str) -> ZaznamRS | None:
    """Stránka /Detail/{id} -> ZaznamRS. None, pokud stránka neobsahuje detail smlouvy."""
    doc = lxml_html.fromstring(obsah)
    tabulky = doc.xpath('//table[@id="invalidItemWarn"]')
    if not tabulky:
        return None
    tabulka = tabulky[0]
    radky: dict[str, object] = {}
    for tr in tabulka.xpath("./tbody/tr | ./tr"):
        tds = tr.xpath("./td")
        if len(tds) == 2:
            radky.setdefault(_text(tds[0]), tds[1])

    zakladni = radky.get("Základní informace")
    zakladni_text = _text(zakladni)
    platny = "Toto je platná smlouva" in zakladni_text
    m_cas = re.search(r"Zveřejněna\s+(\d{1,2}\.\d{1,2}\.\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?)", zakladni_text)
    cas_zverejneni = None
    if m_cas:
        d = _datum(m_cas.group(1))
        hodiny = [int(x) for x in m_cas.group(2).split(":")] + [0]
        cas_zverejneni = datetime(d.year, d.month, d.day, hodiny[0], hodiny[1], hodiny[2], tzinfo=PRAHA)
    m_ids = re.search(r"ID smlouvy\s+(\d+)", zakladni_text)
    m_idv = re.search(r"ID Verze:\s*(\d+)", zakladni_text)
    if m_idv and m_idv.group(1) != str(id_verze):
        raise ValueError(f"stránka detailu {id_verze} popisuje verzi {m_idv.group(1)}")
    datum_uzavreni = None
    cislo = None
    for div in zakladni.xpath("./div") if zakladni is not None else []:
        t = _text(div)
        if t.startswith("Uzavřena"):
            datum_uzavreni = _datum(t)
            # za číslem smlouvy může následovat "Smlouvu schválil <jméno>" – jméno schvalovatele nepřebíráme
            t = re.split(r"\s*(?:,\s*existuje související smlouva|Smlouvu schválil)", t)[0]
            m_c = re.search(r"číslo smlouvy\s+(.+)$", t)
            cislo = m_c.group(1).strip(" ,") if m_c else None

    predmet = None
    h3 = tabulka.xpath("preceding-sibling::h3[1]")
    if h3:
        predmet = _text(h3[0]) or None

    subjekty = _parsuj_strany(radky.get("Publikující strana do Rejstříku smluv"))
    subjekt = subjekty[0] if subjekty else None
    ostatni: list[StranaRS] = []
    for stitek, td in radky.items():
        if stitek.startswith(("Plátce", "Plátci", "Příjemce", "Příjemci")):
            ostatni += _parsuj_strany(td)
    smluvni_strany: list[StranaRS] = []
    for s in ostatni:
        if subjekt is not None and _stejna_strana(s, subjekt):
            subjekt.platce = subjekt.platce or s.platce
            subjekt.prijemce = subjekt.prijemce or s.prijemce
            continue
        if not any(_stejna_strana(s, x) for x in smluvni_strany):
            smluvni_strany.append(s)

    hodnota_bez = hodnota_s = cizi = None
    cizi_mena = duvod = None
    poznamky = ["částky na zrcadle zobrazeny zaokrouhlené na celé jednotky měny"]
    td_h = radky.get("Hodnota smlouvy")
    for p in td_h.xpath("./p") if td_h is not None else []:
        t = _text(p)
        if t.startswith("Cena bez DPH"):
            hodnota_bez = na_decimal(t.split(":", 1)[1])
        elif t.startswith("Cena s DPH"):
            hodnota_s = na_decimal(t.split(":", 1)[1])
        elif t.startswith("Důvod neuvedení ceny"):
            duvod = t.split(":", 1)[1].strip() or None
        else:
            m = re.search(r":\s*([\d\s .,]+)\s*([A-Z]{3})\b", t)
            if m:
                cizi, cizi_mena = na_decimal(m.group(1)), m.group(2)
            else:
                poznamky.append(f"neznámý údaj o hodnotě: {t[:120]}")

    prilohy: list[PrilohaRS] = []
    td_p = radky.get("Přílohy")
    for blok in td_p.xpath('.//div[contains(@class, "bs-callout")]') if td_p is not None else []:
        h4 = blok.xpath(".//h4")
        nazev = (h4[0].get("title") or _text(h4[0])) if h4 else ""
        original = blok.xpath('.//a[normalize-space()="Originál"]/@href')
        kopie = blok.xpath('.//a[contains(@href, "KopiePrilohy")]/@href')
        sha = None
        if kopie:
            sha = (parse_qs(urlsplit(kopie[0]).query).get("hash") or [None])[0]
        prilohy.append(
            PrilohaRS(
                nazev=nazev,
                sha256=sha.lower() if sha and re.fullmatch(r"[0-9a-fA-F]{64}", sha) else None,
                url_original=original[0] if original else None,
                url_stazeni=urljoin(HS_URL, kopie[0]) if kopie else None,
            )
        )

    navazany = None
    for stitek, td in radky.items():
        if stitek.startswith("Provázané smlouvy"):
            navazany = ",".join(sorted(set(re.findall(r"/Detail/(\d+)", lxml_html.tostring(td, encoding="unicode")))))

    return ZaznamRS(
        id_verze=str(id_verze),
        id_smlouvy=m_ids.group(1) if m_ids else None,
        odkaz=odkaz_rs(id_verze),
        cas_zverejneni=cas_zverejneni,
        subjekt=subjekt,
        smluvni_strany=smluvni_strany,
        predmet=predmet,
        datum_uzavreni=datum_uzavreni,
        cislo_smlouvy=cislo,
        hodnota_bez_dph=hodnota_bez,
        hodnota_vcetne_dph=hodnota_s,
        cizi_mena_hodnota=cizi,
        cizi_mena=cizi_mena,
        duvod_neuvedeni_ceny=duvod,
        navazany_zaznam=navazany,
        prilohy=prilohy,
        platny=platny,
        zdroj=ZDROJ,
        poznamky=poznamky,
    )


@dataclass
class VysledekHledani:
    id_verze: str
    podepsano: date | None
    zverejneno: date | None
    hodnota_s_dph: object


_CISLOVKY = {"jeden": 1, "jedna": 1, "dva": 2, "dvě": 2, "tři": 3, "čtyři": 4}


def parsuj_vyhledavani(obsah: str) -> tuple[int, list[VysledekHledani]]:
    doc = lxml_html.fromstring(obsah)
    vysledky = []
    for tr in doc.xpath('//tr[contains(concat(" ", normalize-space(@class), " "), " first ")]'):
        tds = tr.xpath("./td")
        odkazy = tr.xpath('.//a[starts-with(@href, "/Detail/")]/@href')
        if len(tds) < 6 or not odkazy:
            continue
        idv = re.match(r"/Detail/(\d+)", odkazy[0]).group(1)
        vysledky.append(
            VysledekHledani(idv, _datum(_text(tds[1])), _datum(_text(tds[2])), na_decimal(_text(tds[5])))
        )
    text = re.sub(r"\s+", " ", doc.text_content())
    m = re.search(r"Nalezené smlouvy\s+(\S+(?:\s\d{3})*)\s+výsled", text)
    celkem = len(vysledky)
    if m:
        hodnota = m.group(1).replace(" ", " ").replace(" ", "")
        celkem = int(hodnota) if hodnota.isdigit() else _CISLOVKY.get(m.group(1).lower(), celkem)
    return celkem, vysledky


class HlidacRS:
    """Registr smluv přes zrcadlo Hlídač státu – jen pro pilot (D-030) a vývojový vzorek (D-040);
    v provozu a pro publikovaná data výhradně oficiální zdroje."""

    def __init__(self, stahovac: Stahovac, *, pilot: bool = False, vyvojovy_vzorek: bool = False):
        if not (pilot or vyvojovy_vzorek):
            raise PermissionError(
                "zrcadlo Hlídač státu je povoleno jen pro pilot (D-030) a vývojový vzorek (D-040); použijte OficialniRS"
            )
        self.s = stahovac

    def stranka_detailu(self, id_verze: str | int) -> Odpoved:
        return self.s.ziskej(ZDROJ, f"{HS_URL}/Detail/{id_verze}")

    def detail(self, id_verze: str | int) -> tuple[ZaznamRS | None, Odpoved]:
        odp = self.stranka_detailu(id_verze)
        if odp.status != 200:
            return None, odp
        return parsuj_detail(odp.text(), str(id_verze)), odp

    def hledej(self, dotaz: str, max_stran: int = 3) -> tuple[int, list[VysledekHledani]]:
        vsechny: list[VysledekHledani] = []
        celkem = 0
        for strana_c in range(1, max_stran + 1):
            params = {"Q": dotaz} if strana_c == 1 else {"q": dotaz, "page": strana_c}
            odp = self.s.ziskej(ZDROJ, f"{HS_URL}/HledatSmlouvy", params=params)
            if odp.status != 200:
                break
            celkem, radky = parsuj_vyhledavani(odp.text())
            vsechny += radky
            if len(vsechny) >= celkem or not radky:
                break
        return celkem, vsechny

    def kopie_prilohy(self, id_verze: str, priloha: PrilohaRS) -> Odpoved | None:
        if not priloha.url_stazeni:
            return None
        return self.s.ziskej(ZDROJ, priloha.url_stazeni, timeout=(20, 300))
