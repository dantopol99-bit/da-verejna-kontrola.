"""Připojení k PostgreSQL a aplikace SQL migrací (db/migrace/NNNN_*.sql).

Migrace jsou čisté SQL soubory aplikované v pořadí čísla. Aplikovaný soubor se už nesmí změnit:
runner si pamatuje jeho SHA-256 a při neshodě skončí chybou (změna = nová migrace).
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.datetime import DateDumper, DateLoader, DatetimeDumper, TimestamptzLoader

from pvk.config import KOREN, nastaveni

ADRESAR_MIGRACI = KOREN / "db" / "migrace"

# Bitemporální intervaly končí hodnotou 'infinity', kterou Python neumí; mapujeme ji na date.max /
# datetime.max (a zpět), aby šlo s otevřenými intervaly pracovat bez výjimek.
MAX_CAS = datetime.max.replace(tzinfo=UTC)
MIN_CAS = datetime.min.replace(tzinfo=UTC)


class _DatumSNekonecnemDumper(DateDumper):
    def dump(self, obj: date) -> bytes:
        if obj == date.max:
            return b"infinity"
        if obj == date.min:
            return b"-infinity"
        return super().dump(obj)


class _DatumSNekonecnemLoader(DateLoader):
    def load(self, data) -> date:
        if data == b"infinity":
            return date.max
        if data == b"-infinity":
            return date.min
        return super().load(data)


class _CasSNekonecnemDumper(DatetimeDumper):
    def dump(self, obj: datetime) -> bytes:
        if obj == MAX_CAS:
            return b"infinity"
        if obj == MIN_CAS:
            return b"-infinity"
        return super().dump(obj)


class _CasSNekonecnemLoader(TimestamptzLoader):
    def load(self, data) -> datetime:
        if data == b"infinity":
            return MAX_CAS
        if data == b"-infinity":
            return MIN_CAS
        return super().load(data)


psycopg.adapters.register_dumper(date, _DatumSNekonecnemDumper)
psycopg.adapters.register_loader("date", _DatumSNekonecnemLoader)
psycopg.adapters.register_dumper(datetime, _CasSNekonecnemDumper)
psycopg.adapters.register_loader("timestamptz", _CasSNekonecnemLoader)


class ChybaMigrace(RuntimeError):
    pass


def pripoj(database_url: str | None = None, **kwargs) -> psycopg.Connection:
    url = database_url or nastaveni().database_url
    return psycopg.connect(url, row_factory=dict_row, **kwargs)


@contextmanager
def spojeni(database_url: str | None = None) -> Iterator[psycopg.Connection]:
    conn = pripoj(database_url)
    try:
        yield conn
    finally:
        conn.close()


def soubory_migraci(adresar: Path = ADRESAR_MIGRACI) -> list[Path]:
    soubory = sorted(p for p in adresar.glob("*.sql") if p.name[:4].isdigit())
    cisla = [p.name[:4] for p in soubory]
    if len(cisla) != len(set(cisla)):
        raise ChybaMigrace(f"duplicitní čísla migrací: {cisla}")
    return soubory


def migruj(conn: psycopg.Connection, adresar: Path = ADRESAR_MIGRACI) -> list[str]:
    """Aplikuje dosud neaplikované migrace. Vrací jména nově aplikovaných souborů."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS public.pvk_migrace (
              soubor      text PRIMARY KEY,
              sha256      char(64) NOT NULL,
              aplikovano  timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute("SELECT soubor, sha256 FROM public.pvk_migrace")
        aplikovane = {r["soubor"]: r["sha256"].strip() for r in cur.fetchall()}
    conn.commit()

    nove: list[str] = []
    for soubor in soubory_migraci(adresar):
        obsah = soubor.read_bytes()
        otisk = hashlib.sha256(obsah).hexdigest()
        if soubor.name in aplikovane:
            if aplikovane[soubor.name] != otisk:
                raise ChybaMigrace(
                    f"migrace {soubor.name} byla po aplikaci změněna (SHA-256 nesouhlasí). "
                    "Aplikované migrace se nemění – vytvořte novou."
                )
            continue
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(obsah.decode("utf-8"))
                cur.execute(
                    "INSERT INTO public.pvk_migrace (soubor, sha256) VALUES (%s, %s)", (soubor.name, otisk)
                )
        nove.append(soubor.name)
    return nove


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    prikaz = argv[0] if argv else "migrate"
    if prikaz != "migrate":
        print("použití: python -m pvk.db migrate", file=sys.stderr)
        return 2
    with spojeni() as conn:
        nove = migruj(conn)
    print("migrace: " + (", ".join(nove) if nove else "vše aktuální"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
