"""Registry příjemců dotací: IS ReD (MF/GFŘ), Seznam operací 2021–2027 (MMR), SZIF.

Jednotka výběru pro P4 je příjemce. Záznamy fyzických osob se do raw ukládají bez jména,
příjmení a roku narození (D-009); u podnikajících fyzických osob zůstává IČO.
"""

from __future__ import annotations

import csv
import gzip
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape

import openpyxl

from pvk.http import Odpoved, Stahovac
from pvk.ico import normalizuj_ico
from pvk.kotva import PRAVNI_FORMY_FO


@dataclass
class Prijemce:
    registr: str
    id_ve_zdroji: str
    nazev: str | None
    ico: str | None
    ico_ve_zdroji: str | None
    pravni_forma: str | None
    je_fyzicka_osoba: bool
    zaznam: dict  # původní záznam zdroje (pro raw)
    redigovat: tuple[str, ...] = ()


# --- IS ReD --------------------------------------------------------------------------------------

RED_ZDROJ = "red"
RED_CKAN = "https://red.fs.gov.cz/opendata/api/3/action/package_show"
RED_BALICKY = {"prijemce": "prijemce-pomoci", "dotace": "dotace", "pravni_forma": "pravni-forma"}
RED_OSOBNI_POLE = ("jmeno", "prijmeni", "rokNarozeni")


class ReD:
    def __init__(self, stahovac: Stahovac):
        self.s = stahovac

    def url_csv(self, balicek: str) -> str:
        odp = self.s.ziskej(RED_ZDROJ, RED_CKAN, params={"id": RED_BALICKY[balicek]})
        if odp.status != 200:
            raise RuntimeError(f"ReD: katalog {balicek} nedostupný ({odp.status} {odp.chyba})")
        for r in json.loads(odp.obsah())["result"]["resources"]:
            url = r.get("url", "")
            if url.endswith(".csv.gz"):
                return url.replace("://red.financnisprava.cz/", "://red.fs.gov.cz/")
        raise RuntimeError(f"ReD: balíček {balicek} nemá CSV")

    def soubor(self, balicek: str) -> Odpoved:
        odp = self.s.ziskej(RED_ZDROJ, self.url_csv(balicek), timeout=(20, 1800))
        if odp.status != 200:
            raise RuntimeError(f"ReD: {balicek} se nepodařilo stáhnout ({odp.status} {odp.chyba})")
        return odp

    @staticmethod
    def radky(odp: Odpoved) -> Iterator[dict]:
        with gzip.open(odp.cesta, "rt", encoding="utf-8", newline="") as f:
            yield from csv.DictReader(f)

    def pravni_formy(self) -> dict[str, str]:
        """iriPravniForma -> kód právní formy (číselník ČSÚ)."""
        return {r["iriPravniForma"]: r["pravniFormaKod"] for r in self.radky(self.soubor("pravni_forma"))}

    def prijemci_s_dotaci(self, delka_dni: int = 365) -> tuple[list[Prijemce], dict]:
        """Rámec P4 pro ReD: příjemci s alespoň jednou dotací podepsanou v posledních `delka_dni`
        dnech dostupných dat (ReD se publikuje se zpožděním; konec okna = nejnovější datum podpisu)."""
        dotace = self.soubor("dotace")
        posledni_podpis_prijemce: dict[str, str] = {}
        posledni_podpis = ""
        podpis_po_exportu = 0
        # datum exportu je shodné pro celý soubor; podpis po něm je chyba dat, ne nejnovější záznam
        datum_exportu = (next(self.radky(dotace), {}).get("datumExportu") or "")[:10]
        for r in self.radky(dotace):
            podpis = (r.get("podpisDatum") or "")[:10]
            if not podpis:
                continue
            if datum_exportu and podpis > datum_exportu:
                podpis_po_exportu += 1  # chyba kvality dat: podpis "v budoucnosti"
                continue
            posledni_podpis = max(posledni_podpis, podpis)
            if podpis >= "2023-01-01" and podpis > posledni_podpis_prijemce.get(r["iriPrijemce"], ""):
                posledni_podpis_prijemce[r["iriPrijemce"]] = podpis
        do = date.fromisoformat(posledni_podpis) + timedelta(days=1)
        od = do - timedelta(days=delka_dni)
        aktivni = {k for k, v in posledni_podpis_prijemce.items() if od.isoformat() <= v < do.isoformat()}
        formy = self.pravni_formy()
        prijemce_soubor = self.soubor("prijemce")
        prijemci = []
        for r in self.radky(prijemce_soubor):
            if r["iriPrijemce"] not in aktivni:
                continue
            kod = formy.get(r.get("iriPravniForma") or "")
            fo = kod in PRAVNI_FORMY_FO or bool((r.get("jmeno") or r.get("prijmeni")) and not r.get("obchodniNazev"))
            prijemci.append(
                Prijemce(
                    registr=RED_ZDROJ,
                    id_ve_zdroji=r["iriPrijemce"].rsplit("/", 1)[-1],
                    nazev=r.get("obchodniNazev") or None,
                    ico=normalizuj_ico(r.get("ico")),
                    ico_ve_zdroji=r.get("ico") or None,
                    pravni_forma=kod,
                    je_fyzicka_osoba=fo,
                    zaznam={**r, "_url_souboru": prijemce_soubor.url},
                    redigovat=RED_OSOBNI_POLE if fo else (),
                )
            )
        prijemci.sort(key=lambda p: p.id_ve_zdroji)
        meta = {
            "soubor_prijemce": prijemce_soubor.url,
            "soubor_prijemce_sha256": prijemce_soubor.sha256,
            "soubor_dotace": dotace.url,
            "soubor_dotace_sha256": dotace.sha256,
            "posledni_podpis_v_datech": posledni_podpis,
            "datum_exportu": datum_exportu,
            "podpis_po_datu_exportu": podpis_po_exportu,
            "okno_od": od,
            "okno_do": do,
            "ramec": len(prijemci),
        }
        return prijemci, meta


# --- Seznam operací 2021–2027 (dotaceeu.cz) ------------------------------------------------------

EU_ZDROJ = "dotaceeu_2127"
EU_STRANKA = "https://www.dotaceeu.cz/cs/statistiky-a-analyzy/seznam-operaci-(prijemcu)"
_RE_ODKAZ_21 = re.compile(
    r'<a[^>]+href="(/getmedia/[^"]+Seznam-operaci_List-o[fd]-Operations_21\.xlsx\.aspx\?ext=\.xlsx)"[^>]*>(.*?)</a>',
    re.S,
)


class SeznamOperaci:
    def __init__(self, stahovac: Stahovac):
        self.s = stahovac

    def posledni_soubor(self) -> tuple[str, date | None]:
        odp = self.s.ziskej(EU_ZDROJ, EU_STRANKA)
        if odp.status != 200:
            raise RuntimeError(f"dotaceeu.cz nedostupné ({odp.status} {odp.chyba})")
        kandidati = []
        for m in _RE_ODKAZ_21.finditer(odp.text()):
            text = unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
            d = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
            datum = date(int(d.group(3)), int(d.group(2)), int(d.group(1))) if d else None
            kandidati.append((datum or date.min, "https://www.dotaceeu.cz" + unescape(m.group(1))))
        if not kandidati:
            raise RuntimeError("dotaceeu.cz: odkaz na seznam operací 21+ nenalezen")
        datum, url = max(kandidati)
        return url, (datum if datum != date.min else None)

    def prijemci(self) -> tuple[list[Prijemce], dict]:
        url, datum = self.posledni_soubor()
        odp = self.s.ziskej(EU_ZDROJ, url, timeout=(20, 900))
        if odp.status != 200:
            raise RuntimeError(f"dotaceeu.cz: soubor nedostupný ({odp.status})")
        wb = openpyxl.load_workbook(odp.cesta, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        hlavicka = None
        unikatni: dict[tuple[str, str], Prijemce] = {}
        for radek in ws.iter_rows(values_only=True):
            if hlavicka is None:
                if radek and "IČ příjemce" in [str(c).strip() if c is not None else "" for c in radek]:
                    hlavicka = [str(c).strip() if c is not None else "" for c in radek]
                continue
            zaznam = {h: v for h, v in zip(hlavicka, radek, strict=False) if h}
            nazev = (zaznam.get("Příjemce - název") or "").strip() if isinstance(zaznam.get("Příjemce - název"), str) else None
            if not nazev or nazev == "Beneficiary name":
                continue
            ico_zdroj = zaznam.get("IČ příjemce")
            ico = normalizuj_ico(ico_zdroj)
            klic = (ico or "", nazev)
            if klic in unikatni:
                continue
            forma = str(zaznam.get("Právní forma příjemce") or "")
            fo = "fyzick" in forma.lower()
            unikatni[klic] = Prijemce(
                registr=EU_ZDROJ,
                id_ve_zdroji=(
                    f"{ico or '-'}|{nazev}" if not fo else f"FO|{zaznam.get('Registrační číslo projektu') or ico or '-'}"
                ),
                nazev=nazev,
                ico=ico,
                ico_ve_zdroji=str(ico_zdroj) if ico_zdroj is not None else None,
                pravni_forma=forma or None,
                je_fyzicka_osoba=fo,
                zaznam={
                    "Příjemce - název": nazev,
                    "IČ příjemce": ico_zdroj,
                    "Právní forma příjemce": forma,
                    "PSČ příjemce": zaznam.get("PSČ příjemce"),
                    "Registrační číslo projektu": zaznam.get("Registrační číslo projektu"),
                    "_url_souboru": url,
                },
                redigovat=("Příjemce - název", "PSČ příjemce") if fo else (),
            )
        wb.close()
        prijemci = sorted(unikatni.values(), key=lambda p: p.id_ve_zdroji)
        return prijemci, {"soubor": url, "soubor_sha256": odp.sha256, "datum_souboru": datum, "ramec": len(prijemci)}


# --- SZIF ----------------------------------------------------------------------------------------

SZIF_ZDROJ = "szif"
SZIF_OPENDATA = "https://szif.gov.cz/cs/CmOpendata"
SZIF_SOUBOR = "/apa_anon/cs/dokumenty_ke_stazeni/pkp/spd/opendata/spd2025czk.csv"


def je_antibot_vyzva(obsah: bytes) -> bool:
    """F5/TSPD JavaScriptová výzva místo dat (neobcházíme ji)."""
    zacatek = obsah[:4000].decode("utf-8", "replace")
    return "/TSPD/" in zacatek or "window[\"bobcmn\"]" in zacatek


class SZIF:
    def __init__(self, stahovac: Stahovac):
        self.s = stahovac

    def zkus_stahnout(self) -> tuple[Odpoved, str]:
        """Vrací (odpověď, stav): 'ok' | 'antibot' | 'nedostupne'."""
        odp = self.s.ziskej(SZIF_ZDROJ, SZIF_OPENDATA, params={"rid": SZIF_SOUBOR}, pokusy=1)
        if odp.status != 200 or odp.cesta is None:
            return odp, "nedostupne"
        if je_antibot_vyzva(odp.obsah()):
            return odp, "antibot"
        return odp, "ok"
