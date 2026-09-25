"""Adaptér na kotvu (Firemní databázi): subjekt_podle_ico().

Platforma veřejné kontroly nevede vlastní registr subjektů. Údaje o subjektu (název, právní forma,
vznik/zánik) se berou z kotvy v okamžiku potřeby a neukládají se – ani do raw, ani na disk.

V pilotu kotva ještě není připojená, proto AresKotva volá přímo veřejné REST API ARES.
Později se nahradí implementací DbKotva (dotaz do databáze kotvy); rozhraní Kotva zůstává.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pvk.config import nastaveni
from pvk.ico import ico_platne, normalizuj_ico

ARES_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest"

# Právní formy fyzických osob (číselník ČSÚ): 100–108 podnikající FO, 424/425 zahraniční FO.
PRAVNI_FORMY_FO = frozenset({"100", "101", "102", "103", "104", "105", "106", "107", "108", "424", "425"})


@dataclass(frozen=True)
class SubjektKotvy:
    ico: str
    nazev: str
    pravni_forma: str | None
    je_fyzicka_osoba: bool | None
    datum_vzniku: date | None
    datum_zaniku: date | None
    zdroj: str


class Kotva(Protocol):
    def subjekt_podle_ico(self, ico: str) -> SubjektKotvy | None: ...

    def hledej_podle_nazvu(self, nazev: str, max_vysledku: int = 5) -> list[SubjektKotvy]: ...


def je_fyzicka_osoba(pravni_forma: str | None) -> bool | None:
    if not pravni_forma:
        return None
    return pravni_forma in PRAVNI_FORMY_FO


def _datum(hodnota: str | None) -> date | None:
    try:
        return date.fromisoformat(hodnota[:10]) if hodnota else None
    except ValueError:
        return None


class AresKotva:
    """Kotva přes ARES REST API (pilot). Pouze paměťová cache po dobu běhu, žádná lokální kopie."""

    ROZESTUP = 0.35

    def __init__(self, user_agent: str | None = None, timeout: float = 30):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent or nastaveni().user_agent
        self.session.headers["Accept"] = "application/json"
        verify = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
        if verify:
            self.session.verify = verify
        self.session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=4,
                    backoff_factor=2,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=frozenset({"GET", "POST"}),
                    raise_on_status=False,
                )
            ),
        )
        self.timeout = timeout
        self._posledni = 0.0
        self._zamek = threading.Lock()
        self._cache: dict[str, SubjektKotvy | None] = {}

    def _pockej(self) -> None:
        with self._zamek:
            cekani = self._posledni + self.ROZESTUP - time.monotonic()
            if cekani > 0:
                time.sleep(cekani)
            self._posledni = time.monotonic()

    @staticmethod
    def _z_ares(d: dict) -> SubjektKotvy:
        pf = d.get("pravniForma")
        return SubjektKotvy(
            ico=d["ico"],
            nazev=d.get("obchodniJmeno") or "",
            pravni_forma=pf,
            je_fyzicka_osoba=je_fyzicka_osoba(pf),
            datum_vzniku=_datum(d.get("datumVzniku")),
            datum_zaniku=_datum(d.get("datumZaniku")),
            zdroj="ares",
        )

    def subjekt_podle_ico(self, ico: str) -> SubjektKotvy | None:
        ico_n = normalizuj_ico(ico)
        if ico_n is None or not ico_platne(ico_n):
            return None
        if ico_n in self._cache:
            return self._cache[ico_n]
        self._pockej()
        r = self.session.get(f"{ARES_URL}/ekonomicke-subjekty/{ico_n}", timeout=self.timeout)
        if r.status_code in (400, 404):
            vysledek = None
        else:
            r.raise_for_status()
            vysledek = self._z_ares(r.json())
        self._cache[ico_n] = vysledek
        return vysledek

    def hledej_podle_nazvu(self, nazev: str, max_vysledku: int = 5) -> list[SubjektKotvy]:
        if not nazev or not nazev.strip():
            return []
        self._pockej()
        r = self.session.post(
            f"{ARES_URL}/ekonomicke-subjekty/vyhledat",
            json={"obchodniJmeno": nazev.strip(), "start": 0, "pocet": max_vysledku},
            timeout=self.timeout,
        )
        if r.status_code in (400, 404):
            return []
        r.raise_for_status()
        return [self._z_ares(d) for d in r.json().get("ekonomickeSubjekty", []) if d.get("ico")]


class DbKotva:
    """Budoucí implementace: dotaz do databáze kotvy (Firemní databáze) přes KOTVA_DATABASE_URL.

    Schéma kotvy tento repozitář nezná a do kotvy nezasahuje; implementace vznikne, až bude
    dohodnuté rozhraní (pohled/funkce kotvy vracející údaje subjektu k IČO).
    """

    def __init__(self, database_url: str):
        self.database_url = database_url

    def subjekt_podle_ico(self, ico: str) -> SubjektKotvy | None:
        raise NotImplementedError("DbKotva: rozhraní kotvy zatím není dohodnuté (viz docs/decisions.md)")

    def hledej_podle_nazvu(self, nazev: str, max_vysledku: int = 5) -> list[SubjektKotvy]:
        raise NotImplementedError("DbKotva: rozhraní kotvy zatím není dohodnuté (viz docs/decisions.md)")


@lru_cache(maxsize=1)
def vychozi_kotva() -> Kotva:
    n = nastaveni()
    if n.kotva == "db":
        if not n.kotva_database_url:
            raise RuntimeError("PVK_KOTVA=db vyžaduje KOTVA_DATABASE_URL")
        return DbKotva(n.kotva_database_url)
    return AresKotva(n.user_agent)


def subjekt_podle_ico(ico: str, kotva: Kotva | None = None) -> SubjektKotvy | None:
    """Údaje o subjektu k IČO z kotvy (v pilotu z ARES). None, pokud IČO neexistuje nebo je neplatné."""
    return (kotva or vychozi_kotva()).subjekt_podle_ico(ico)
