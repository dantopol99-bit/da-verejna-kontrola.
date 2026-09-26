"""Vrstva raw: pouze INSERT. Každý záznam má zdroj, ID ve zdroji, soubor/URL, čas stažení a hash.

Neměnnost vynucuje databáze (triggery, SQLSTATE PV001). Tento modul jen zapisuje:
  * zajisti_zdroj()  – evidence zdroje (idempotentní),
  * zapis_stazeni()  – log každého stažení včetně neúspěšných,
  * zapis_zaznam()   – zdrojový záznam; stejný záznam (stejný hash) se podruhé nevloží.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb


def _json_default(o: object) -> object:
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    raise TypeError(f"nelze serializovat {type(o).__name__}")


def kanonicky_json(obj: object) -> bytes:
    """Kanonická podoba záznamu pro hash: seřazené klíče, UTF-8, bez mezer."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default).encode(
        "utf-8"
    )


def hash_zaznamu(obj: object) -> str:
    return hashlib.sha256(kanonicky_json(obj)).hexdigest()


def _jsonb(obj: object) -> Jsonb:
    return Jsonb(json.loads(kanonicky_json(obj)))


def zajisti_zdroj(
    conn: psycopg.Connection,
    kod: str,
    nazev: str,
    spravce: str,
    url: str,
    licence: str | None = None,
    poznamka: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO raw.zdroj (kod, nazev, spravce, url, licence, poznamka)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (kod) DO NOTHING
        """,
        (kod, nazev, spravce, url, licence, poznamka),
    )


def zapis_stazeni(
    conn: psycopg.Connection,
    *,
    zdroj: str,
    url: str,
    cas_stazeni: datetime,
    http_status: int | None,
    sha256: str | None = None,
    velikost: int | None = None,
    soubor: str | None = None,
    content_type: str | None = None,
    chyba: str | None = None,
    metoda: str = "GET",
    parametry: Mapping | None = None,
    hlavicky: Mapping[str, str] | None = None,
    beh_id: int | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO raw.stazeni (zdroj, url, metoda, parametry, cas_stazeni, http_status, sha256, velikost,
                                 soubor, content_type, chyba, hlavicky, beh_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            zdroj,
            url,
            metoda,
            _jsonb(parametry) if parametry is not None else None,
            cas_stazeni,
            http_status,
            sha256,
            velikost,
            soubor,
            content_type,
            chyba,
            _jsonb(dict(hlavicky)) if hlavicky else None,
            beh_id,
        ),
    ).fetchone()
    return row["id"] if isinstance(row, Mapping) else row[0]


def zapis_zaznam(
    conn: psycopg.Connection,
    *,
    zdroj: str,
    id_ve_zdroji: str,
    url: str,
    cas_stazeni: datetime,
    obsah: Mapping,
    format: str,
    stazeni_id: int | None = None,
    redigovat: Iterable[str] = (),
    ulozeny_obsah: Mapping | None = None,
    beh_id: int | None = None,
) -> int:
    """Uloží zdrojový záznam. Hash se počítá z původního záznamu; pole v `redigovat`
    (osobní údaje fyzických osob bez IČO) se do obsahu neuloží a jejich jména se zapíší do `redigovano`.
    U vnořených polí předá volající už redigovaný `ulozeny_obsah` a v `redigovat` cesty k vynechaným polím.
    Vrací id řádku (nového, nebo již existujícího se stejným hashem)."""
    redigovat = sorted(set(redigovat))
    h = hash_zaznamu(obsah)
    if ulozeny_obsah is None:
        ulozeny_obsah = {k: v for k, v in obsah.items() if k not in redigovat}
    row = conn.execute(
        """
        INSERT INTO raw.zaznam (zdroj, id_ve_zdroji, url, cas_stazeni, hash, stazeni_id, format, obsah, redigovano,
                                beh_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (zdroj, id_ve_zdroji, hash) DO NOTHING
        RETURNING id
        """,
        (zdroj, str(id_ve_zdroji), url, cas_stazeni, h, stazeni_id, format, _jsonb(ulozeny_obsah), redigovat, beh_id),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT id FROM raw.zaznam WHERE zdroj = %s AND id_ve_zdroji = %s AND hash = %s",
            (zdroj, str(id_ve_zdroji), h),
        ).fetchone()
    return row["id"] if isinstance(row, Mapping) else row[0]


def posledni_zaznam(conn: psycopg.Connection, zdroj: str, id_ve_zdroji: str) -> Mapping | None:
    return conn.execute(
        """
        SELECT * FROM raw.zaznam WHERE zdroj = %s AND id_ve_zdroji = %s
        ORDER BY cas_stazeni DESC, id DESC LIMIT 1
        """,
        (zdroj, str(id_ve_zdroji)),
    ).fetchone()
