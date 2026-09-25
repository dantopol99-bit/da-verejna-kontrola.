"""Společný kontext běhu pilotu: databáze, stahovač, metodika, seedy, ukládání mezivýsledků."""

from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from pvk.config import KOREN, Nastaveni, nastaveni
from pvk.core import zajisti_metodiku
from pvk.db import migruj, pripoj
from pvk.http import Stahovac
from pvk.zdroje import zaregistruj_zdroje

KOD_METODIKY = "pilot-2026.09"
LOG = logging.getLogger("pvk.pilot")


def _json_default(o: object) -> object:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o).__name__)


@dataclass
class Kontext:
    conn: psycopg.Connection
    nast: Nastaveni
    stahovac: Stahovac
    metodika: dict
    metodika_id: str
    seed: int
    od: date
    do: date
    adresar_vysledku: Path = field(default_factory=lambda: KOREN / "data" / "pilot")

    @classmethod
    def vytvor(cls, offline: bool = False) -> Kontext:
        nast = nastaveni()
        conn = pripoj(nast.database_url)
        migruj(conn)
        zaregistruj_zdroje(conn)
        cesta_metodiky = KOREN / "metodika" / f"{KOD_METODIKY}.json"
        definice = json.loads(cesta_metodiky.read_text(encoding="utf-8"))
        dokument = KOREN / definice["dokument"]
        otisk = hashlib.sha256(dokument.read_bytes()).hexdigest() if dokument.is_file() else None
        metodika_id = zajisti_metodiku(conn, definice, otisk)
        conn.commit()
        p = definice["parametry"]
        adresar = nast.data_dir / "pilot"
        adresar.mkdir(parents=True, exist_ok=True)
        return cls(
            conn=conn,
            nast=nast,
            stahovac=Stahovac(conn, nast, offline=offline),
            metodika=p,
            metodika_id=str(metodika_id),
            seed=nast.pilot_seed,
            od=date.fromisoformat(p["obdobi_od"]),
            do=date.fromisoformat(p["obdobi_do"]),
            adresar_vysledku=adresar,
        )

    def rng(self, ucel: str) -> random.Random:
        """Odvozený generátor pro konkrétní výběr – stejný seed, stejné pořadí losování."""
        odvozeny = int(hashlib.sha256(f"{self.seed}:{ucel}".encode()).hexdigest()[:12], 16)
        return random.Random(odvozeny)

    def uloz(self, jmeno: str, data: object) -> Path:
        cesta = self.adresar_vysledku / f"{jmeno}.json"
        cesta.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=_json_default), encoding="utf-8")
        return cesta

    def nacti(self, jmeno: str) -> dict | list | None:
        cesta = self.adresar_vysledku / f"{jmeno}.json"
        return json.loads(cesta.read_text(encoding="utf-8")) if cesta.is_file() else None
