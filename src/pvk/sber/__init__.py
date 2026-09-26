"""Sběr zdrojových dat do raw (blok 2): stahovače, evidence běhů, jeden příkaz pro všechny zdroje.

Každý běh stahovače jednoho zdroje má evidenci v raw.beh (začátek, období, parametry)
a raw.beh_konec (konec, stav, počty, chyby). Před sběrem proběhne jeden rychlý test dostupnosti
bez opakování; nedostupný zdroj se přeskočí se stavem `preskoceno` (neobchází se, D-033).
Záznamy se zapisují jen přes pvk.raw (pouze INSERT; stejný záznam se podruhé nevloží).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import psycopg

from pvk.http import Stahovac

LOG = logging.getLogger("pvk.sber")


@dataclass
class Vysledek:
    pocet_zaznamu: int = 0
    pocet_ve_zdroji: int | None = None  # údaj zdroje (např. X-Total-Count), pokud ho zdroj uvádí
    chyby: list[str] = field(default_factory=list)
    poznamka: str | None = None
    parametry: dict = field(default_factory=dict)  # upřesnění běhu (skutečné okno, soubory)


@dataclass
class Beh:
    """Kontext jednoho běhu: stahovač s nastaveným beh_id a zápis záznamů s evidencí původu."""

    conn: psycopg.Connection
    stahovac: Stahovac
    id: int
    zdroj: str
    od: date
    do: date
    vysledek: Vysledek = field(default_factory=Vysledek)

    def zaznam(self, id_ve_zdroji: str, url: str, odp, obsah: dict, format: str, **kw) -> None:
        from pvk import raw

        raw.zapis_zaznam(
            self.conn,
            zdroj=self.zdroj,
            id_ve_zdroji=id_ve_zdroji,
            url=url,
            cas_stazeni=odp.cas_stazeni,
            obsah=obsah,
            format=format,
            stazeni_id=odp.stazeni_id,
            beh_id=self.id,
            **kw,
        )
        self.vysledek.pocet_zaznamu += 1
        if self.vysledek.pocet_zaznamu % 1000 == 0:
            self.conn.commit()


def zahaj_beh(conn: psycopg.Connection, zdroj: str, od: date | None, do: date | None, parametry: dict) -> int:
    row = conn.execute(
        "INSERT INTO raw.beh (zdroj, obdobi_od, obdobi_do, parametry) VALUES (%s, %s, %s, %s::jsonb) RETURNING id",
        (zdroj, od, do, json.dumps(parametry, ensure_ascii=False, default=str)),
    ).fetchone()
    conn.commit()
    return row["id"] if isinstance(row, dict) else row[0]


def ukonci_beh(conn: psycopg.Connection, beh_id: int, stav: str, v: Vysledek) -> None:
    nove = conn.execute("SELECT count(*) AS n FROM raw.zaznam WHERE beh_id = %s", (beh_id,)).fetchone()
    conn.execute(
        """
        INSERT INTO raw.beh_konec (beh_id, stav, pocet_zaznamu, pocet_novych, pocet_ve_zdroji, chyby, poznamka)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
        """,
        (
            beh_id,
            stav,
            v.pocet_zaznamu,
            nove["n"] if isinstance(nove, dict) else nove[0],
            v.pocet_ve_zdroji,
            json.dumps([c[:2000] for c in v.chyby], ensure_ascii=False),
            v.poznamka,
        ),
    )
    conn.commit()


@dataclass
class Sberac:
    """Stahovač jednoho zdroje: URL rychlého testu dostupnosti a funkce sběru za období."""

    zdroj: str
    url_dostupnosti: str
    sber: Callable[[Beh], None]
    popis: str


def spust(conn: psycopg.Connection, stahovac: Stahovac, sberac: Sberac, od: date, do: date) -> tuple[int, str]:
    """Jeden běh jednoho zdroje. Nikdy nespadne kvůli zdroji: chyba se zapíše do evidence běhu."""
    beh_id = zahaj_beh(conn, sberac.zdroj, od, do, {"stahovac": sberac.popis})
    stahovac.beh_id = beh_id
    beh = Beh(conn, stahovac, beh_id, sberac.zdroj, od, do)
    try:
        # jeden rychlý pokus bez opakování; výsledek je v raw.stazeni (beh_id)
        odp = stahovac.ziskej(sberac.zdroj, sberac.url_dostupnosti, obnov=True, pokusy=0, timeout=(15, 30))
        if odp.status != 200:
            beh.vysledek.chyby.append(f"zdroj nedostupný: {sberac.url_dostupnosti} ({odp.status or odp.chyba})")
            beh.vysledek.poznamka = "přeskočeno – zdroj z této sítě nedostupný; ochrany se neobcházejí (D-033)"
            stav = "preskoceno"
        else:
            sberac.sber(beh)
            stav = "chyba" if beh.vysledek.chyby else "uspech"
    except Exception as e:  # noqa: BLE001 – každá chyba zdroje patří do evidence běhu, ne do pádu make sber
        conn.rollback()
        LOG.exception("sběr %s selhal", sberac.zdroj)
        beh.vysledek.chyby.append(f"{type(e).__name__}: {e}")
        stav = "chyba"
    finally:
        stahovac.beh_id = None
    if beh.vysledek.parametry:
        beh.vysledek.poznamka = "; ".join(
            filter(None, [beh.vysledek.poznamka, json.dumps(beh.vysledek.parametry, ensure_ascii=False, default=str)])
        )
    ukonci_beh(conn, beh_id, stav, beh.vysledek)
    LOG.info("sběr %-14s %-10s záznamů %d", sberac.zdroj, stav, beh.vysledek.pocet_zaznamu)
    return beh_id, stav
