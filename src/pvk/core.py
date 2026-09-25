"""Vrstva core: bitemporální zápis entit.

Jediná cesta změny je SQL funkce core.zapis_verzi(): uzavře překrývající se aktuální verze, zachová
jejich zbytky mimo nový interval a vloží novou verzi. Přímý UPDATE/DELETE databáze odmítne (PV002).

Dotaz "jak to bylo platné ke dni D, jak jsme to věděli v čase T":
    WHERE valid_from <= D AND D < valid_to AND recorded_from <= T AND T < recorded_to
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from uuid import UUID

import psycopg

from pvk.raw import kanonicky_json

TABULKY_ENTIT = (
    "zdrojovy_zaznam",
    "subjekt",
    "tok",
    "tok_zdroj",
    "castka",
    "udalost",
    "limit",
    "metodika_verze",
)

NEKONECNO = date.max  # psycopg převádí date.max na 'infinity' jen explicitně, viz _datum()


def _datum(d: date | None) -> str:
    return "infinity" if d is None or d == NEKONECNO else d.isoformat()


def zapis_verzi(
    conn: psycopg.Connection,
    tabulka: str,
    data: Mapping,
    valid_from: date,
    valid_to: date | None = None,
) -> UUID:
    """Zapíše novou verzi entity (nebo založí entitu, pokud data neobsahují <tabulka>_id)."""
    if tabulka not in TABULKY_ENTIT:
        raise ValueError(f"{tabulka} není entita core")
    row = conn.execute(
        "SELECT core.zapis_verzi(%s::regclass, %s::jsonb, %s::date, %s::date) AS klic",
        (f"core.{tabulka}", kanonicky_json(data).decode("utf-8"), _datum(valid_from), _datum(valid_to)),
    ).fetchone()
    klic = row["klic"] if isinstance(row, Mapping) else row[0]
    return klic if isinstance(klic, UUID) else UUID(str(klic))


def subjekt_pro_ico(conn: psycopg.Connection, ico: str) -> UUID:
    """Subjekt (jen odkaz na IČO). Existuje-li aktuální verze, vrátí její klíč, jinak založí novou."""
    row = conn.execute(
        "SELECT subjekt_id FROM core.subjekt_aktualni WHERE ico = %s AND valid_to = 'infinity' LIMIT 1", (ico,)
    ).fetchone()
    if row:
        return row["subjekt_id"] if isinstance(row, Mapping) else row[0]
    return zapis_verzi(conn, "subjekt", {"ico": ico}, date(1990, 1, 1))


def metodika_pro_kod(conn: psycopg.Connection, kod: str) -> Mapping | None:
    return conn.execute(
        """
        SELECT metodika_verze_id, kod, parametry FROM core.metodika_verze_aktualni
        WHERE kod = %s AND valid_to = 'infinity'
        """,
        (kod,),
    ).fetchone()


def zajisti_metodiku(conn: psycopg.Connection, definice: Mapping, dokument_sha256: str | None = None) -> UUID:
    """Zapíše verzi metodiky z definice (metodika/<kod>.json); idempotentní."""
    existujici = metodika_pro_kod(conn, definice["kod"])
    data = {
        "kod": definice["kod"],
        "popis": definice["popis"],
        "parametry": json.loads(kanonicky_json(definice["parametry"])),
        "dokument": definice.get("dokument"),
        "dokument_sha256": dokument_sha256,
    }
    if existujici:
        data["metodika_verze_id"] = str(existujici["metodika_verze_id"])
    return zapis_verzi(conn, "metodika_verze", data, date.fromisoformat(definice["platnost_od"]))
