"""Stahovače jednotlivých zdrojů (blok 2 – raw sběr). Popis zdrojů v docs/sources.md.

Dostupné z cloudu (ověřovací běh proběhl): VVZ, IS ReD, seznam operací 2021–2027.
Z cloudových adres blokované (stahovač otestován na vzorových datech, poběží z české sítě):
registr smluv, NEN, ISVZ, CEDR.

Osobní údaje (D-009): u stran bez IČO se do raw neukládá název/jméno ani adresa, kontaktní údaje
osob (e-mail, telefon, přihlašovací jména) se neukládají vůbec; hash je vždy z původního záznamu.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import os
import re
import time
import zipfile
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import openpyxl
from lxml import etree

from pvk import raw
from pvk.sber import LOG, Beh, Sberac
from pvk.zdroje import dotace as dotace_zdroje
from pvk.zdroje import registr_smluv as rs
from pvk.zdroje import vvz

# --- společné pomocníky --------------------------------------------------------------------------

KONTAKTNI_KLICE = ("email", "e-mail", "telefon", "kontaktniosob", "rodnecislo", "datumnarozeni")
IDENTIFIKACE_STRANY = ("nazev", "jmeno", "prijmeni", "adresa", "datovaschranka", "psc", "obec", "ulice")


def _ma_ico(strana: dict) -> bool:
    return any("ico" in k.lower() and v not in (None, "", [], {}) for k, v in strana.items())


def rediguj(obj, strany: frozenset[str] = frozenset(), vzdy: frozenset[str] = frozenset(), cesta: str = ""):
    """Vrací (kopie bez osobních údajů, seznam cest vynechaných polí).

    * klíče ve `vzdy` a kontaktní údaje (e-mail, telefon, kontaktní osoba…) se vynechají všude,
    * ve slovnících pod klíči ze `strany` (smluvní strana, dodavatel…) bez IČO se vynechá
      název/jméno a adresa – může jít o fyzickou osobu (D-009)."""
    vynechano: list[str] = []
    if isinstance(obj, list):
        vysledek = []
        for i, x in enumerate(obj):
            v, p = rediguj(x, strany, vzdy, f"{cesta}[{i}]")
            vysledek.append(v)
            vynechano += p
        return vysledek, vynechano
    if not isinstance(obj, dict):
        return obj, vynechano
    klic_strany = cesta.rsplit(".", 1)[-1].split("[", 1)[0]
    bez_ico = klic_strany in strany and not _ma_ico(obj)
    vysledek = {}
    for k, v in obj.items():
        kl = k.lower().lstrip("@")
        pod = f"{cesta}.{k}" if cesta else k
        if k in vzdy or any(x in kl for x in KONTAKTNI_KLICE) or (
            bez_ico and any(x in kl for x in IDENTIFIKACE_STRANY) and v not in (None, "")
        ):
            vynechano.append(pod)
            continue
        vysledek[k], p = rediguj(v, strany, vzdy, pod)
        vynechano += p
    return vysledek, vynechano


def xml_na_dict(el):
    """XML element -> dict (atributy s '@', opakované elementy jako seznam, jmenné prostory vynechány)."""
    deti = [c for c in el if isinstance(c.tag, str)]
    text = (el.text or "").strip()
    if not deti and not el.attrib:
        return text or None
    d: dict = {f"@{rs._lokalni(k)}": v for k, v in el.attrib.items()}
    for c in deti:
        k, v = rs._lokalni(c.tag), xml_na_dict(c)
        if k in d:
            d[k] = d[k] if isinstance(d[k], list) else [d[k]]
            d[k].append(v)
        else:
            d[k] = v
    if text and not deti:
        d["#text"] = text
    return d


def _mesice(od: date, do: date) -> list[tuple[int, int]]:
    mesice, d = [], date(od.year, od.month, 1)
    while d < do:
        mesice.append((d.year, d.month))
        d = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return mesice


def _dny(od: date, do: date) -> Iterator[date]:
    for i in range((do - od).days):
        yield od + timedelta(days=i)


RE_ODKAZ = re.compile(r"""href=["']([^"'#]+)["']""", re.I)


def odkazy(html: str, zaklad: str) -> list[str]:
    return list(dict.fromkeys(urljoin(zaklad, unescape(h)) for h in RE_ODKAZ.findall(html)))


# --- Registr smluv (oficiální XML dumpy) ----------------------------------------------------------

RS_STRANY = frozenset({"smluvniStrana", "subjekt"})


def sber_registr_smluv(beh: Beh) -> None:
    """Denní dumpy za období; každý <zaznam> (verze záznamu smlouvy) je jeden záznam raw."""
    for den in _dny(beh.od, beh.do):
        url = f"{rs.DATA_URL}/dump_{den:%Y_%m_%d}.xml"
        odp = beh.stahovac.ziskej(rs.ZDROJ, url, obnov=True, timeout=(20, 900))
        if odp.status != 200:
            beh.vysledek.chyby.append(f"{url}: {odp.status or odp.chyba}")
            continue
        for zaznam, xml in rs.parsuj_dump(odp.cesta):
            puvodni = xml_na_dict(etree.fromstring(xml))
            ulozeny, vynechano = rediguj(puvodni, RS_STRANY)
            beh.zaznam(zaznam.id_verze, url, odp, puvodni, "xml", ulozeny_obsah=ulozeny, redigovat=vynechano)


# --- VVZ (veřejné API webu Věstníku) --------------------------------------------------------------

VVZ_LIMIT = 250  # API vrací nejvýš 250 položek na stránku
VVZ_VZDY = frozenset({"owner", "createdBy", "updatedBy", "uzivatelVvzLogin"})  # osoby zadávající formulář
VVZ_STRANY = frozenset({"zadavatele", "dodavatele"})


def sber_vvz(beh: Beh) -> None:
    """Všechny formuláře uveřejněné ve VVZ v období (souhrn formuláře z vyhledávání).
    Počet se porovnává s hlavičkou X-Total-Count."""
    filtry = {
        "formGroup": "vz",
        "form": "vz",
        "workflowPlace": "UVEREJNENO_VVZ",
        "data.datumUverejneniVvz[gte]": beh.od.isoformat(),
        "data.datumUverejneniVvz[lt]": beh.do.isoformat(),
        "order[variableId]": "asc",
    }
    strana, posledni = 1, 1
    while strana <= posledni:
        odp = beh.stahovac.ziskej(
            vvz.ZDROJ, f"{vvz.API}/api/submissions/search", params={**filtry, "page": strana, "limit": VVZ_LIMIT},
            obnov=True,
        )
        if odp.status != 200:
            beh.vysledek.chyby.append(f"{odp.url}: {odp.status or odp.chyba}")
            return
        hl = odp.hlavicky or {}
        if strana == 1:
            if "x-total-count" in hl:
                beh.vysledek.pocet_ve_zdroji = int(hl["x-total-count"])
            posledni = int(hl.get("x-last-page") or 1)
        polozky = json.loads(odp.obsah())
        for p in polozky:
            ulozeny, vynechano = rediguj(p, VVZ_STRANY, VVZ_VZDY)
            beh.zaznam(p.get("variableId") or p["id"], odp.url, odp, p, "json", ulozeny_obsah=ulozeny, redigovat=vynechano)
        if not polozky:
            break
        strana += 1


# --- VVZ: detail formulářů (úplný obsah eForms), s navazováním ------------------------------------

VVZ_DETAIL_ZDROJ = "vvz_detail"
VVZ_DETAIL_CEKANI = (30, 60, 120)  # s; opakování stažení formuláře po chybě (nad opakováním v pvk.http)
VVZ_DETAIL_MAX_CHYB_ZA_SEBOU = 3  # tolik formulářů za sebou nestaženo -> běh končí, zbytek příště
RE_EFORMS_KONTAKT = re.compile(r"^BT-(502|503|506|739)-")  # kontaktní místo, telefon, e-mail, fax
EFORMS_STRANA_BEZ_ICO = frozenset({"BT-500-Organization-Company", "ND-CompanyAddress"})


def rediguj_eforms(obj, cesta: str = ""):
    """Detail formuláře VVZ bez osobních údajů (D-035, D-038): kontaktní údaje (BT-502/503/506/739)
    a osoby zadávající formulář všude, údaje o skutečných majitelích (UBO) celé, u organizace bez IČO
    (BT-501) název a adresa. Vrací (kopie, seznam cest vynechaných polí)."""
    vynechano: list[str] = []
    if isinstance(obj, list):
        vysledek = []
        for i, x in enumerate(obj):
            v, p = rediguj_eforms(x, f"{cesta}[{i}]")
            vysledek.append(v)
            vynechano += p
        return vysledek, vynechano
    if not isinstance(obj, dict):
        return obj, vynechano
    bez_ico = "ND-CompanyLegalEntity" in obj or "BT-500-Organization-Company" in obj  # uzel ND-Company
    if bez_ico:
        bez_ico = not any(
            isinstance(le, dict) and le.get("BT-501-Organization-Company")
            for le in vvz.seznam(obj.get("ND-CompanyLegalEntity"))
        )
    vysledek = {}
    for k, v in obj.items():
        pod = f"{cesta}.{k}" if cesta else k
        if k in VVZ_VZDY or RE_EFORMS_KONTAKT.match(k) or "UBO" in k or (bez_ico and k in EFORMS_STRANA_BEZ_ICO):
            vynechano.append(pod)
            continue
        vysledek[k], p = rediguj_eforms(v, pod)
        vynechano += p
    return vysledek, vynechano


def formulare_vvz(conn, od: date, do: date) -> list[tuple[str, str, bool]]:
    """Formuláře VVZ uveřejněné v období podle souhrnů v raw (sběr `vvz`), v pořadí evidenčních čísel:
    (evidenční číslo formuláře, ID podání v API, detail už je v raw). Datum uveřejnění se porovnává
    jako datum v čase ČR, stejně jako filtr API."""
    radky = conn.execute(
        """
        SELECT DISTINCT ON (s.id_ve_zdroji) s.id_ve_zdroji AS formular, s.obsah->>'id' AS submission,
               EXISTS (SELECT 1 FROM raw.zaznam d WHERE d.zdroj = %s AND d.id_ve_zdroji = s.id_ve_zdroji) AS hotovo
        FROM raw.zaznam s
        WHERE s.zdroj = %s
          AND left(s.obsah->'data'->>'datumUverejneniVvz', 10) >= %s
          AND left(s.obsah->'data'->>'datumUverejneniVvz', 10) < %s
        ORDER BY s.id_ve_zdroji, s.cas_stazeni DESC, s.id DESC
        """,
        (VVZ_DETAIL_ZDROJ, vvz.ZDROJ, od.isoformat(), do.isoformat()),
    ).fetchall()
    return [(r["formular"], r["submission"], r["hotovo"]) for r in radky]


def _stahni_detail(beh: Beh, submission: str):
    """Stažení detailu s opakováním po chybě spojení, 429 a 5xx (čekání VVZ_DETAIL_CEKANI, nejvýš do
    časového limitu běhu). Dříve úspěšně stažený detail se bere z raw.stazeni (nestahuje se znovu)."""
    api = vvz.VVZ(beh.stahovac)
    for cekani in (*VVZ_DETAIL_CEKANI, None):
        odp, deti = api.deti(submission)
        if odp.status == 200 or (odp.status is not None and odp.status < 500 and odp.status != 429):
            return odp, deti
        if cekani is None or beh.zbyva_sekund() < cekani:
            return odp, deti
        LOG.warning("VVZ detail %s: %s, další pokus za %d s", submission, odp.status or odp.chyba, cekani)
        time.sleep(cekani)
    raise AssertionError


def sber_vvz_detail(beh: Beh) -> None:
    """Úplný obsah formulářů eForms (`children/search`) pro formuláře VVZ uveřejněné v období (seznam
    ze souhrnů v raw, proto běží po sběru `vvz`). Navazuje: formulář, jehož detail už je v raw, se
    přeskočí, takže přerušený nebo časově omezený běh pokračuje dalším nestaženým formulářem a nic se
    nestahuje dvakrát. Záznam = odpověď API pro jeden formulář (ID = evidenční číslo formuláře)."""
    formulare = formulare_vvz(beh.conn, beh.od, beh.do)
    hotovo_pred = sum(1 for *_x, hotovo in formulare if hotovo)
    p = beh.vysledek.parametry
    p.update({"formularu_v_obdobi": len(formulare), "hotovo_pred_behem": hotovo_pred})
    beh.vysledek.pocet_ve_zdroji = len(formulare)
    if not formulare:
        beh.vysledek.chyby.append("VVZ detail: v raw nejsou souhrny formulářů za období (nejdřív sběr vvz)")
    stazeno = chyb_za_sebou = 0
    for formular, submission, hotovo in formulare:
        if hotovo:
            continue
        if beh.zbyva_sekund() <= 0:
            p["ukonceno"] = "časový limit běhu"
            break
        odp, deti = _stahni_detail(beh, submission)
        if odp.status != 200:
            beh.vysledek.chyby.append(f"{formular} {odp.url}: {odp.status or odp.chyba}")
            chyb_za_sebou += 1
            if chyb_za_sebou >= VVZ_DETAIL_MAX_CHYB_ZA_SEBOU:
                p["ukonceno"] = f"{chyb_za_sebou} formuláře za sebou nestaženy – zbytek příští běh"
                break
            continue
        chyb_za_sebou = 0
        puvodni = {"formular": formular, "submission": submission, "deti": deti}
        ulozeny, vynechano = rediguj_eforms(puvodni)
        beh.zaznam(formular, odp.url, odp, puvodni, "json", ulozeny_obsah=ulozeny, redigovat=vynechano)
        beh.conn.commit()  # každý formulář hned: přerušený běh naváže dalším
        stazeno += 1
    p.update({"stazeno_v_behu": stazeno, "zbyva": len(formulare) - hotovo_pred - stazeno})


UPLNOST_POLI = {  # název ukazatele -> test na údajích detailu (vvz.udaje_detailu)
    "IČO zadavatele": lambda u: bool(u["ico_zadavatelu"]),
    "IČO dodavatele": lambda u: bool(u["ico_dodavatelu"]),
    "předpokládaná hodnota": lambda u: bool(u["predpokladana_hodnota"]),
    "vysoutěžená cena": lambda u: bool(u["vysoutezena_cena"]),
    "počet nabídek": lambda u: bool(u["pocet_nabidek"]),
    "druh řízení": lambda u: bool(u["druh_rizeni"]),
    "lhůta pro nabídky / žádosti": lambda u: bool(u["lhuty"]["podani_nabidek"] or u["lhuty"]["zadosti_o_ucast"]),
    "CPV": lambda u: bool(u["cpv"]),
    "evidenční číslo zakázky (VVZ)": lambda u: bool(u["ev_cislo_zakazky"]),
    "identifikátor NIPEZ": lambda u: bool(u["identifikator_nipez"]),
}


def uplnost_vvz_detail(conn, od: date, do: date) -> dict:
    """Stav navazujícího sběru a úplnost stažených detailů za období: počty formulářů (v období / hotovo /
    zbývá) a pro tři rámce (všechny stažené detaily, oznámení o výsledku BT-03 = result, výsledky
    s vybraným dodavatelem) počet detailů s vyplněným údajem."""
    formulare = formulare_vvz(conn, od, do)
    radky = conn.execute(
        """
        SELECT DISTINCT ON (d.id_ve_zdroji) d.obsah AS detail, s.obsah AS souhrn
        FROM raw.zaznam d
        JOIN LATERAL (SELECT obsah FROM raw.zaznam s WHERE s.zdroj = %s AND s.id_ve_zdroji = d.id_ve_zdroji
                      ORDER BY s.cas_stazeni DESC, s.id DESC LIMIT 1) s ON true
        WHERE d.zdroj = %s AND d.id_ve_zdroji = ANY(%s)
        ORDER BY d.id_ve_zdroji, d.cas_stazeni DESC, d.id DESC
        """,
        (vvz.ZDROJ, VVZ_DETAIL_ZDROJ, [f for f, _s, hotovo in formulare if hotovo]),
    ).fetchall()
    udaje = [vvz.udaje_detailu(r["detail"], r["souhrn"]) for r in radky]
    ramce = {
        "všechny stažené detaily": udaje,
        "oznámení o výsledku (BT-03 = result)": [u for u in udaje if u["vysledek"]],
        "výsledky s vybraným dodavatelem": [u for u in udaje if u["vysledek"] and u["vybran_dodavatel"]],
    }
    return {
        "formularu_v_obdobi": len(formulare),
        "hotovo": len(udaje),
        "zbyva": len(formulare) - len(udaje),
        "bez_eforms": sum(1 for u in udaje if not u["eforms"]),
        "ramce": {nazev: {"zaklad": len(us), **{pole: sum(1 for u in us if test(u)) for pole, test in UPLNOST_POLI.items()}}
                  for nazev, us in ramce.items()},
    }


# --- ISVZ (otevřená data Registru veřejných zakázek) ----------------------------------------------

ISVZ_ZDROJ = "isvz"
ISVZ_OPENDATA = "https://isvz.nipez.cz/opendata"
RE_DATOVY_SOUBOR = re.compile(r"\.(json|xml|zip|csv)(\.gz)?$", re.I)
ISVZ_STRANY = frozenset({"dodavatel", "dodavatele", "uchazec", "uchazeci", "subdodavatel", "prijemce"})
ID_KLICE = ("id", "ID", "Id", "evidencniCislo", "evCislo", "evCisloZakazky", "evCisloFormulare", "kod", "identifikator")


def _soubor_za_mesic(url: str, rok: int, mesic: int) -> bool:
    jmeno = url.rsplit("/", 1)[-1]
    vzory = (f"{rok}-{mesic:02d}", f"{rok}_{mesic:02d}", f"{rok}{mesic:02d}", f"{mesic:02d}-{rok}", f"{mesic:02d}_{rok}")
    return any(v in jmeno for v in vzory)


def zaznamy_souboru(cesta: Path, jmeno: str = "") -> Iterator[tuple[dict, str]]:
    """Záznamy datového souboru neznámé přesné struktury: ZIP/GZIP se rozbalí; JSON = položky seznamu
    (i vnořeného), XML = opakující se element pod kořenem, CSV = řádky. Vrací (záznam, formát)."""
    data = cesta.read_bytes()
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for clen in z.namelist():
                if RE_DATOVY_SOUBOR.search(clen):
                    docasny = cesta.with_name(cesta.name + ".clen")
                    docasny.write_bytes(z.read(clen))
                    try:
                        yield from zaznamy_souboru(docasny, clen)
                    finally:
                        docasny.unlink()
        return
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    zacatek = data.lstrip()[:1]
    if zacatek in (b"[", b"{"):
        obj = json.loads(data)
        while isinstance(obj, dict):
            seznamy = [v for v in obj.values() if isinstance(v, list)]
            if not seznamy:
                yield obj, "json"
                return
            obj = max(seznamy, key=len)
        for x in obj:
            yield (x if isinstance(x, dict) else {"hodnota": x}), "json"
    elif zacatek == b"<":
        koren = etree.fromstring(data, parser=etree.XMLParser(huge_tree=True))
        while len([c for c in koren if isinstance(c.tag, str)]) == 1:
            koren = next(c for c in koren if isinstance(c.tag, str))
        deti = [c for c in koren if isinstance(c.tag, str)]
        tag = Counter(c.tag for c in deti).most_common(1)[0][0] if deti else None
        for c in deti:
            if c.tag == tag:
                d = xml_na_dict(c)
                yield (d if isinstance(d, dict) else {"hodnota": d}), "xml"
    else:
        text = data.decode("utf-8-sig", "replace")
        oddelovac = ";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ","
        for r in csv.DictReader(io.StringIO(text), delimiter=oddelovac):
            yield r, "csv"


def id_zaznamu(zaznam: dict, predpona: str = "") -> str:
    for k in ID_KLICE:
        v = zaznam.get(k)
        if isinstance(v, (str, int)) and str(v).strip():
            return f"{predpona}{v}"
    return f"{predpona}sha256:{raw.hash_zaznamu(zaznam)}"


def sber_isvz(beh: Beh) -> None:
    """Měsíční soubory otevřených dat RVZ za měsíce období. Odkazy na soubory se hledají na stránce
    otevřených dat (název souboru obsahuje rok a měsíc), takže stahovač nezávisí na přesné cestě."""
    stranka = beh.stahovac.ziskej(ISVZ_ZDROJ, ISVZ_OPENDATA)
    soubory = [u for u in odkazy(stranka.text(), ISVZ_OPENDATA) if RE_DATOVY_SOUBOR.search(u.split("?")[0])]
    for rok, mesic in _mesice(beh.od, beh.do):
        za_mesic = [u for u in soubory if _soubor_za_mesic(u.split("?")[0], rok, mesic)]
        if not za_mesic:
            beh.vysledek.chyby.append(f"ISVZ: na {ISVZ_OPENDATA} není soubor za {rok}-{mesic:02d}")
        for url in za_mesic:
            odp = beh.stahovac.ziskej(ISVZ_ZDROJ, url, obnov=True, timeout=(20, 1800))
            if odp.status != 200:
                beh.vysledek.chyby.append(f"{url}: {odp.status or odp.chyba}")
                continue
            for zaznam, fmt in zaznamy_souboru(odp.cesta):
                ulozeny, vynechano = rediguj(zaznam, ISVZ_STRANY)
                beh.zaznam(id_zaznamu(zaznam), url, odp, zaznam, fmt, ulozeny_obsah=ulozeny, redigovat=vynechano)


# --- NEN (XML data profilů zadavatelů) ------------------------------------------------------------

NEN_ZDROJ = "nen"
NEN_WEB = "https://nen.nipez.cz"
NEN_PROFILY = f"{NEN_WEB}/profily-zadavatelu-platne"
RE_PROFIL = re.compile(r"/profil/([A-Za-z0-9_.\-]+)")
NEN_STRANY = frozenset({"dodavatel", "uchazec", "subdodavatel"})
NEN_MAX_STRAN_SEZNAMU = 2000


def profily_nen(beh: Beh) -> list[str]:
    """Kódy profilů: PVK_SBER_NEN_PROFILY (čárkami), jinak seznam platných profilů v NEN (i stránkovaný)."""
    if os.environ.get("PVK_SBER_NEN_PROFILY"):
        return [p.strip() for p in os.environ["PVK_SBER_NEN_PROFILY"].split(",") if p.strip()]
    profily: dict[str, None] = {}
    fronta, videno = [NEN_PROFILY], set()
    while fronta and len(videno) < NEN_MAX_STRAN_SEZNAMU:
        url = fronta.pop(0)
        videno.add(url)
        odp = beh.stahovac.ziskej(NEN_ZDROJ, url)
        if odp.status != 200:
            beh.vysledek.chyby.append(f"{url}: {odp.status or odp.chyba}")
            continue
        for u in odkazy(odp.text(), url):
            if m := RE_PROFIL.search(u):
                profily.setdefault(m.group(1))
            elif "profily-zadavatelu-platne" in u and "page" in u and u not in videno and u not in fronta:
                fronta.append(u)
    return list(profily)


def sber_nen(beh: Beh) -> None:
    """XML data profilu zadavatele (XMLdataVZ, vyhláška č. 345/2023 Sb.) za období pro každý profil v NEN;
    každý element <zakazka> je jeden záznam raw."""
    profily = profily_nen(beh)
    if not profily:
        beh.vysledek.chyby.append("NEN: seznam profilů zadavatelů je prázdný")
    konec = beh.do - timedelta(days=1)  # XMLdataVZ má období včetně posledního dne
    for kod in profily:
        url = f"{NEN_WEB}/profil/{kod}/XMLdataVZ"
        odp = beh.stahovac.ziskej(
            NEN_ZDROJ, url, params={"od": f"{beh.od:%d%m%Y}", "do": f"{konec:%d%m%Y}"}, obnov=True, timeout=(20, 300)
        )
        if odp.status != 200:
            beh.vysledek.chyby.append(f"{odp.url}: {odp.status or odp.chyba}")
            continue
        koren = etree.fromstring(odp.obsah(), parser=etree.XMLParser(huge_tree=True))
        for el in koren.iter():
            if isinstance(el.tag, str) and rs._lokalni(el.tag) == "zakazka":
                zaznam = xml_na_dict(el)
                vz = zaznam.get("VZ") if isinstance(zaznam.get("VZ"), dict) else zaznam
                kod_vz = vz.get("kod_vz_na_profilu") if isinstance(vz, dict) else None
                id_vz = f"{kod}/{kod_vz}" if kod_vz else id_zaznamu(zaznam, f"{kod}/")
                ulozeny, vynechano = rediguj(zaznam, NEN_STRANY)
                beh.zaznam(id_vz, odp.url, odp, zaznam, "xml", ulozeny_obsah=ulozeny, redigovat=vynechano)


# --- registry dotací v CSV: IS ReD a CEDR III -----------------------------------------------------


def _radky_csv(cesta: Path) -> Iterator[dict]:
    otevri = gzip.open if cesta.read_bytes()[:2] == b"\x1f\x8b" else open
    with otevri(cesta, "rt", encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def sber_registru_dotaci(
    beh: Beh,
    urls: dict[str, str],
    sloupce: dict[str, str],
    osobni: tuple[str, ...],
    zmeneno: dict[str, datetime] | None = None,
) -> None:
    """Dotace podepsané v období + jejich příjemci a rozhodnutí (částky).

    `urls`: dotace / prijemce / rozhodnuti -> URL souboru; `sloupce`: id_dotace, id_prijemce,
    id_rozhodnuti, datum (datum podpisu); `zmeneno`: čas poslední změny souboru podle katalogu – dříve
    stažený soubor se znovu nestahuje, pokud se od té doby nezměnil. Když data končí před začátkem období
    (IS ReD se publikuje se zpožděním), použije se stejně dlouhé okno končící posledním datem podpisu
    nejpozději k datu exportu (D-022); skutečné okno se zapíše do evidence běhu."""
    s = sloupce

    def stahni(tabulka: str):
        zmena = (zmeneno or {}).get(tabulka)
        odp = beh.stahovac.ziskej(beh.zdroj, urls[tabulka], timeout=(20, 3600), obnov=zmena is None)
        if odp.z_cache and zmena is not None and odp.cas_stazeni <= zmena:
            odp = beh.stahovac.ziskej(beh.zdroj, urls[tabulka], timeout=(20, 3600), obnov=True)
        if odp.status != 200:
            raise RuntimeError(f"{urls[tabulka]}: {odp.status or odp.chyba}")
        beh.vysledek.parametry[f"{tabulka}_stazeni"] = {"id": odp.stazeni_id, "sha256": odp.sha256,
                                                        "drive_stazeny": odp.z_cache}
        return odp

    dotace = stahni("dotace")
    export = (next(_radky_csv(dotace.cesta), {}).get("datumExportu") or "")[:10]
    posledni = max(
        (p for r in _radky_csv(dotace.cesta) if (p := (r.get(s["datum"]) or "")[:10]) and (not export or p <= export)),
        default="",
    )
    od, do = beh.od, beh.do
    if posledni and date.fromisoformat(posledni) < od:
        do = date.fromisoformat(posledni) + timedelta(days=1)
        od = do - (beh.do - beh.od)
        beh.vysledek.parametry["okno_podle_dat"] = {"datum_exportu": export, "posledni_podpis": posledni,
                                                   "od": od, "do": do}
    id_dotaci, id_prijemcu = set(), set()
    for r in _radky_csv(dotace.cesta):
        podpis = (r.get(s["datum"]) or "")[:10]
        if od.isoformat() <= podpis < do.isoformat():
            beh.zaznam(r.get(s["id_dotace"]) or id_zaznamu(r), dotace.url, dotace, r, "csv")
            id_dotaci.add(r.get(s["id_dotace"]))
            id_prijemcu.add(r.get(s["id_prijemce"]))
    prijemce = stahni("prijemce")
    for r in _radky_csv(prijemce.cesta):
        if r.get(s["id_prijemce"]) in id_prijemcu:
            vynechat = [k for k in osobni if r.get(k)]
            beh.zaznam(r[s["id_prijemce"]], prijemce.url, prijemce, r, "csv", redigovat=vynechat)
    rozhodnuti = stahni("rozhodnuti")
    for r in _radky_csv(rozhodnuti.cesta):
        if r.get(s["id_dotace"]) in id_dotaci:
            beh.zaznam(r.get(s["id_rozhodnuti"]) or id_zaznamu(r), rozhodnuti.url, rozhodnuti, r, "csv")
    beh.vysledek.parametry.update({"dotaci": len(id_dotaci), "prijemcu": len(id_prijemcu)})


RED_BALICKY = {"dotace": "dotace", "prijemce": "prijemce-pomoci", "rozhodnuti": "rozhodnuti"}


def sber_red(beh: Beh) -> None:
    urls, zmeneno = {}, {}
    for tabulka, balicek in RED_BALICKY.items():
        odp = beh.stahovac.ziskej(dotace_zdroje.RED_ZDROJ, dotace_zdroje.RED_CKAN, params={"id": balicek}, obnov=True)
        if odp.status != 200:
            raise RuntimeError(f"ReD: katalog {balicek} nedostupný ({odp.status or odp.chyba})")
        zdroje = [r for r in json.loads(odp.obsah())["result"]["resources"] if r.get("url", "").endswith(".csv.gz")]
        if not zdroje:
            raise RuntimeError(f"ReD: balíček {balicek} nemá CSV")
        urls[tabulka] = zdroje[0]["url"].replace("://red.financnisprava.cz/", "://red.fs.gov.cz/")
        upraveno = zdroje[0].get("last_modified") or zdroje[0].get("metadata_modified")
        beh.vysledek.parametry[f"{tabulka}_upraveno"] = upraveno
        # CKAN uvádí čas v UTC bez časové zóny; bez údaje se soubor stáhne vždy znovu
        zmeneno[tabulka] = datetime.fromisoformat(upraveno).replace(tzinfo=UTC) if upraveno else None
    sloupce = {"id_dotace": "iriDotace", "id_prijemce": "iriPrijemce", "id_rozhodnuti": "iriRozhodnuti",
               "datum": "podpisDatum"}
    sber_registru_dotaci(beh, urls, sloupce, dotace_zdroje.RED_OSOBNI_POLE, zmeneno)


CEDR_ZDROJ = "cedr"
CEDR_INDEX = "https://cedropendata.mfcr.cz/c3lod/cedr/"
CEDR_SOUBORY = {"dotace": "Dotace", "prijemce": "PrijemcePomoci", "rozhodnuti": "Rozhodnuti"}


def sber_cedr(beh: Beh) -> None:
    """CEDR III (historická data, nahrazena IS ReD): soubory Dotace / PrijemcePomoci / Rozhodnuti (CSV.gz).
    Odkazy se berou ze stránky otevřených dat, jinak z konvence c3lod/{Tabulka}.csv.gz."""
    stranka = beh.stahovac.ziskej(CEDR_ZDROJ, CEDR_INDEX)
    nalezene = odkazy(stranka.text(), CEDR_INDEX) if stranka.status == 200 else []
    urls = {}
    for tabulka, jmeno in CEDR_SOUBORY.items():
        kandidati = [u for u in nalezene if re.search(rf"/{jmeno}\.csv(\.gz)?$", u.split("?")[0], re.I)]
        urls[tabulka] = kandidati[0] if kandidati else f"https://cedropendata.mfcr.cz/c3lod/{jmeno}.csv.gz"
    sloupce = {"id_dotace": "idDotace", "id_prijemce": "idPrijemce", "id_rozhodnuti": "idRozhodnuti",
               "datum": "podpisDatum"}
    sber_registru_dotaci(beh, urls, sloupce, ("jmeno", "prijmeni", "rokNarozeni"))


# --- Seznam operací 2021–2027 (dotaceeu.cz) -------------------------------------------------------

EU_OSOBNI = ("Příjemce - název", "PSČ příjemce")
EU_DODAVATEL = ("Název dodavatele veřejné zakázky", "IČ dodavatele veřejné zakázky")
EU_ANGLICKA_HLAVICKA = {"Project registration number", "Beneficiary name"}


def sber_dotaceeu(beh: Beh) -> None:
    """Nejnovější měsíční seznam operací 21+ (XLSX); jeden řádek = projekt × veřejná zakázka v projektu
    (ID = registrační číslo projektu # číslo řádku). U příjemců – fyzických osob se neukládá název ani PSČ,
    u dodavatelů a poddodavatelů bez IČ název (D-009)."""
    url, datum = dotace_zdroje.SeznamOperaci(beh.stahovac).posledni_soubor()
    beh.vysledek.parametry.update({"soubor": url, "datum_souboru": datum})
    odp = beh.stahovac.ziskej(dotace_zdroje.EU_ZDROJ, url, timeout=(20, 900))
    if odp.status != 200:
        raise RuntimeError(f"{url}: {odp.status or odp.chyba}")
    hlavicka = None
    # souborový objekt: openpyxl jinak odmítá soubory bez přípony .xlsx
    with odp.cesta.open("rb") as soubor:
        wb = openpyxl.load_workbook(soubor, read_only=True, data_only=True)
        for radek in wb.worksheets[0].iter_rows(values_only=True):
            bunky = [str(c).strip() if c is not None else "" for c in radek]
            if hlavicka is None:
                if "IČ příjemce" in bunky:
                    hlavicka = bunky
                continue
            zaznam = {h: v for h, v in zip(hlavicka, radek, strict=False) if h}
            reg = zaznam.get("Registrační číslo projektu")
            if not reg or reg in EU_ANGLICKA_HLAVICKA or zaznam.get("Příjemce - název") in EU_ANGLICKA_HLAVICKA:
                continue
            vynechat = []
            if "fyzick" in str(zaznam.get("Právní forma příjemce") or "").lower():
                vynechat += [k for k in EU_OSOBNI if zaznam.get(k) not in (None, "")]
            nazev_dod, ico_dod = EU_DODAVATEL
            if zaznam.get(nazev_dod) and not zaznam.get(ico_dod):
                vynechat.append(nazev_dod)
            if isinstance(zaznam.get("Poddodavatel"), str) and len(zaznam["Poddodavatel"].strip()) > 3:
                vynechat.append("Poddodavatel")  # název bez IČ – může jít o fyzickou osobu
            radek_id = zaznam.get("Číslo řádku")
            id_zaznamu_eu = f"{reg}#{radek_id}" if radek_id not in (None, "") else str(reg)
            beh.zaznam(id_zaznamu_eu, url, odp, zaznam, "xlsx", redigovat=vynechat)
        wb.close()
    if hlavicka is None:
        raise RuntimeError("seznam operací: hlavička s 'IČ příjemce' nenalezena")


# --- registr stahovačů (pořadí = pořadí v make sber) ----------------------------------------------

SBERACE: dict[str, Sberac] = {
    s.zdroj: s
    for s in (
        Sberac(rs.ZDROJ, f"{rs.DATA_URL}/index.xml", sber_registr_smluv, "registr smluv – denní XML dumpy"),
        Sberac(vvz.ZDROJ, f"{vvz.API}/api/submissions/search?formGroup=vz&form=vz&page=1&limit=1", sber_vvz,
               "VVZ – formuláře uveřejněné v období"),
        Sberac(VVZ_DETAIL_ZDROJ, f"{vvz.API}/api/submissions/search?formGroup=vz&form=vz&page=1&limit=1",
               sber_vvz_detail, "VVZ – detail formulářů (eForms), navazuje na předchozí běhy"),
        Sberac(ISVZ_ZDROJ, ISVZ_OPENDATA, sber_isvz, "ISVZ – měsíční otevřená data RVZ"),
        Sberac(NEN_ZDROJ, NEN_PROFILY, sber_nen, "NEN – XML data profilů zadavatelů"),
        Sberac(dotace_zdroje.RED_ZDROJ, f"{dotace_zdroje.RED_CKAN}?id=dotace", sber_red,
               "IS ReD – dotace, příjemci, rozhodnutí"),
        Sberac(CEDR_ZDROJ, CEDR_INDEX, sber_cedr, "CEDR III – dotace, příjemci, rozhodnutí"),
        Sberac(dotace_zdroje.EU_ZDROJ, dotace_zdroje.EU_STRANKA, sber_dotaceeu, "seznam operací 2021–2027"),
    )
}
