"""Kurzy devizového trhu ČNB pro přepočet cizoměnových částek (k datu uzavření).

Roční soubor ČNB (`rok.txt?rok=RRRR`): řádek = den vyhlášení, sloupce `množství kód` (např. `100 JPY`).
Kurz platí ode dne vyhlášení do dalšího vyhlášení, proto se pro datum D bere poslední kurz vyhlášený
nejpozději v den D. Soubory jdou přes pvk.http.Stahovac (log v raw.stazeni, úložiště data/raw).
Nejsou-li kurzy dostupné, vrací se None a částka zůstane nepřepočtená s příznakem.
"""

from __future__ import annotations

import bisect
from datetime import date, datetime
from decimal import Decimal

ZDROJ = "cnb_kurzy"
URL = "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/rok.txt"


def parsuj_rok(text: str) -> dict[str, list[tuple[date, Decimal]]]:
    """Roční soubor -> {měna: [(den vyhlášení, kurz za 1 jednotku)]}; v souboru se může opakovat hlavička."""
    kurzy: dict[str, list[tuple[date, Decimal]]] = {}
    sloupce: list[tuple[str, int]] = []
    for radek in text.splitlines():
        bunky = radek.strip().split("|")
        if not bunky or not bunky[0]:
            continue
        if bunky[0] == "Datum":
            sloupce = []
            for b in bunky[1:]:
                mnozstvi, _, kod = b.partition(" ")
                sloupce.append((kod.strip(), int(mnozstvi)))
            continue
        try:
            den = datetime.strptime(bunky[0], "%d.%m.%Y").date()
        except ValueError:
            continue
        for (kod, mnozstvi), hodnota in zip(sloupce, bunky[1:], strict=False):
            if hodnota.strip():
                kurzy.setdefault(kod, []).append((den, Decimal(hodnota.replace(",", ".")) / mnozstvi))
    for rada in kurzy.values():
        rada.sort()
    return kurzy


class KurzyCNB:
    def __init__(self, stahovac=None):
        self.stahovac = stahovac
        self._kurzy: dict[str, list[tuple[date, Decimal]]] = {}
        self._roky: dict[int, bool] = {}
        self.chyby: list[str] = []

    def nacti_text(self, text: str) -> None:
        for kod, rada in parsuj_rok(text).items():
            self._kurzy.setdefault(kod, []).extend(rada)
            self._kurzy[kod].sort()

    def _zajisti_rok(self, rok: int) -> bool:
        if rok not in self._roky:
            ok = False
            if self.stahovac is not None:
                odp = self.stahovac.ziskej(ZDROJ, URL, params={"rok": rok}, timeout=(15, 60))
                if odp.status == 200:
                    self.nacti_text(odp.text())
                    ok = True
                else:
                    self.chyby.append(f"kurzy ČNB {rok}: {odp.status or odp.chyba}")
            self._roky[rok] = ok
        return self._roky[rok]

    def kurz(self, mena: str, datum: date) -> tuple[Decimal, date] | None:
        """Kurz CZK za 1 jednotku měny platný k datu a den jeho vyhlášení; None = kurz není k dispozici."""
        # kurz k 1. lednu může pocházet z posledního vyhlášení předchozího roku
        self._zajisti_rok(datum.year)
        if datum.month == 1 and datum.day < 10:
            self._zajisti_rok(datum.year - 1)
        rada = self._kurzy.get(mena)
        if not rada:
            return None
        i = bisect.bisect_right(rada, (datum, Decimal("Infinity"))) - 1
        if i < 0 or (datum - rada[i][0]).days > 10:  # žádné vyhlášení v posledních 10 dnech -> nedostupný
            return None
        return rada[i][1], rada[i][0]
