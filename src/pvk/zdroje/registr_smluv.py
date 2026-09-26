"""Registr smluv – oficiální otevřená data (https://data.smlouvy.gov.cz/).

Dumpy XML: měsíční dump_RRRR_MM.xml a denní dump_RRRR_MM_DD.xml, přehled v index.xml.
Kořen <dump> nese metadata dumpu a sekvenci elementů <zaznam> (verze záznamů smluv):

  <zaznam>
    <identifikator><idSmlouvy/><idVerze/></identifikator>
    <odkaz/> <casZverejneni/>
    <smlouva>
      <subjekt><datovaSchranka/><nazev/><ico/><adresa/><utvar/><platce/></subjekt>
      <smluvniStrana>...<prijemce/></smluvniStrana>   (1..n)
      <predmet/> <datumUzavreni/> <cisloSmlouvy/> <schvalil/>
      <hodnotaBezDph/> <hodnotaVcetneDph/> <ciziMena><hodnota/><mena/></ciziMena>
      <navazanyZaznam/>
    </smlouva>
    <prilohy><priloha><nazevSouboru/><hash algoritmus="sha256"/><odkaz/></priloha></prilohy>
    <platnyZaznam>1</platnyZaznam>
  </zaznam>

Parser je nezávislý na jmenném prostoru (ISRS mění verze schématu). Pozn.: z této session nebyl
oficiální zdroj dosažitelný (viz docs/sources.md), parser je ověřen na syntetickém vzorku podle XSD.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

from lxml import etree

from pvk.http import Odpoved, Stahovac
from pvk.zdroje.rs import PrilohaRS, StranaRS, ZaznamRS, na_decimal, odkaz_rs, strana

ZDROJ = "registr_smluv"
DATA_URL = "https://data.smlouvy.gov.cz"


def _lokalni(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _deti(el, jmeno: str) -> list:
    return [c for c in el if _lokalni(c.tag) == jmeno]


def _text(el, jmeno: str) -> str | None:
    if el is None:
        return None
    for c in el:
        if _lokalni(c.tag) == jmeno:
            t = (c.text or "").strip()
            return t or None
    return None


def _bool(hodnota: str | None) -> bool | None:
    if hodnota is None:
        return None
    return hodnota.strip().lower() in {"1", "true"}


def _strana(el, role: str) -> StranaRS:
    return strana(
        _text(el, "nazev"),
        _text(el, "ico"),
        datova_schranka=_text(el, "datovaSchranka"),
        platce=_bool(_text(el, "platce")) if role == "subjekt" else None,
        prijemce=_bool(_text(el, "prijemce")),
    )


def parsuj_zaznam(el) -> ZaznamRS:
    ident = (_deti(el, "identifikator") or [None])[0]
    id_verze = _text(ident, "idVerze")
    smlouva = (_deti(el, "smlouva") or [None])[0]
    subjekt_el = (_deti(smlouva, "subjekt") or [None])[0] if smlouva is not None else None
    cizi_el = (_deti(smlouva, "ciziMena") or [None])[0] if smlouva is not None else None
    prilohy = []
    for pr in _deti(el, "prilohy"):
        for p in _deti(pr, "priloha"):
            hash_el = (_deti(p, "hash") or [None])[0]
            algoritmus = (hash_el.get("algoritmus") or "").lower() if hash_el is not None else ""
            hodnota = (hash_el.text or "").strip().lower() if hash_el is not None else ""
            odkaz = _text(p, "odkaz")
            prilohy.append(
                PrilohaRS(
                    nazev=_text(p, "nazevSouboru") or "",
                    sha256=hodnota if algoritmus in {"sha256", "sha2", ""} and len(hodnota) == 64 else None,
                    url_original=odkaz,
                    url_stazeni=odkaz,
                )
            )
    cas = _text(el, "casZverejneni")
    datum = _text(smlouva, "datumUzavreni") if smlouva is not None else None
    return ZaznamRS(
        id_verze=id_verze or "",
        id_smlouvy=_text(ident, "idSmlouvy"),
        odkaz=_text(el, "odkaz") or odkaz_rs(id_verze),
        cas_zverejneni=datetime.fromisoformat(cas) if cas else None,
        subjekt=_strana(subjekt_el, "subjekt") if subjekt_el is not None else None,
        smluvni_strany=[_strana(s, "strana") for s in _deti(smlouva, "smluvniStrana")] if smlouva is not None else [],
        predmet=_text(smlouva, "predmet"),
        datum_uzavreni=date.fromisoformat(datum[:10]) if datum else None,
        cislo_smlouvy=_text(smlouva, "cisloSmlouvy"),
        hodnota_bez_dph=na_decimal(_text(smlouva, "hodnotaBezDph")),
        hodnota_vcetne_dph=na_decimal(_text(smlouva, "hodnotaVcetneDph")),
        cizi_mena_hodnota=na_decimal(_text(cizi_el, "hodnota")),
        cizi_mena=_text(cizi_el, "mena"),
        duvod_neuvedeni_ceny=None,
        navazany_zaznam=_text(smlouva, "navazanyZaznam"),
        prilohy=prilohy,
        platny=_bool(_text(el, "platnyZaznam")) is not False,
        zdroj=ZDROJ,
    )


def parsuj_dump(cesta: Path | str) -> Iterator[tuple[ZaznamRS, bytes]]:
    """Proudově projde dump a vrací (záznam, XML fragment záznamu)."""
    for _udalost, el in etree.iterparse(str(cesta), events=("end",), huge_tree=True):
        if _lokalni(el.tag) != "zaznam":
            continue
        yield parsuj_zaznam(el), etree.tostring(el, encoding="utf-8")
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]


class OficialniRS:
    def __init__(self, stahovac: Stahovac):
        self.s = stahovac

    def dostupny(self) -> bool:
        """Rychlá zkouška dostupnosti (bez opakování); výsledek se zapíše do raw.stazeni."""
        odp = self.s.ziskej(ZDROJ, f"{DATA_URL}/index.xml", obnov=True, pokusy=0, timeout=(15, 30))
        return odp.status == 200

    def denni_dump(self, den: date) -> Odpoved:
        return self.s.ziskej(ZDROJ, f"{DATA_URL}/dump_{den:%Y_%m_%d}.xml", timeout=(20, 900))

    def vzorek(self, n: int, od: date, do: date, seed: int, pocet_dnu: int = 24) -> list[tuple[ZaznamRS, bytes, Odpoved]]:
        """Dvoustupňový výběr: náhodné dny v období, z platných záznamů jejich denních dumpů prostý
        náhodný výběr n záznamů. Pořadí je deterministické (seed)."""
        rng = random.Random(seed)
        dny = [od + timedelta(days=i) for i in range((do - od).days)]
        rng.shuffle(dny)
        fond: list[tuple[ZaznamRS, bytes, Odpoved]] = []
        pouzite = 0
        for den in dny:
            if pouzite >= pocet_dnu and len(fond) >= 3 * n:
                break
            odp = self.denni_dump(den)
            if odp.status != 200:
                continue
            pouzite += 1
            for z, xml in parsuj_dump(odp.cesta):
                if z.platny and z.cas_zverejneni and od <= z.cas_zverejneni.date() < do:
                    fond.append((z, xml, odp))
        fond.sort(key=lambda x: int(x[0].id_verze or 0))
        return rng.sample(fond, min(n, len(fond)))

    def priloha(self, priloha: PrilohaRS) -> Odpoved | None:
        """Stáhne přílohu z registru smluv a ověří její SHA-256 proti hashi z oficiálních metadat
        (element `hash` v dumpu). Soubor s jiným hashem se odmítne výjimkou NeshodaHashe – do dalšího
        zpracování se nedostane; pokus zůstává zapsaný v raw.stazeni."""
        if not priloha.url_original:
            return None
        odp = self.s.ziskej(ZDROJ, priloha.url_original, timeout=(20, 300))
        if odp.status == 200 and priloha.sha256 and odp.sha256 != priloha.sha256:
            raise NeshodaHashe(priloha.url_original, priloha.sha256, odp)
        return odp


class NeshodaHashe(Exception):
    """Stažená příloha se neshoduje s hashem z oficiálních metadat registru smluv."""

    def __init__(self, url: str, ocekavany: str, odpoved: Odpoved):
        super().__init__(f"{url}: SHA-256 {odpoved.sha256} neodpovídá metadatům registru ({ocekavany})")
        self.url, self.ocekavany, self.skutecny, self.odpoved = url, ocekavany, odpoved.sha256, odpoved
