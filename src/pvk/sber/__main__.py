"""make sber / make sber-stav.

  python -m pvk.sber [--zdroje vvz,red] [--od RRRR-MM-DD] [--do RRRR-MM-DD]
      všechny stahovače za období (výchozí poslední měsíc: [dnes − 1 měsíc, dnes)); nedostupný zdroj
      se přeskočí se záznamem v evidenci běhu. Návratový kód 1 jen při chybě dostupného zdroje.
  python -m pvk.sber stav [--pocet N]
      přehled posledních běhů (raw.beh_prehled).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from zoneinfo import ZoneInfo

from pvk.config import nastaveni
from pvk.db import pripoj
from pvk.http import Stahovac
from pvk.sber import spust
from pvk.sber.sberace import SBERACE
from pvk.zdroje import zaregistruj_zdroje


def mesic_zpet(d: date) -> date:
    rok, mesic = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    for den in (d.day, 30, 29, 28):
        try:
            return date(rok, mesic, den)
        except ValueError:
            continue
    raise AssertionError


def vychozi_obdobi(dnes: date | None = None) -> tuple[date, date]:
    do = date.fromisoformat(os.environ["PVK_SBER_DO"]) if os.environ.get("PVK_SBER_DO") else (dnes or date.today())
    od = date.fromisoformat(os.environ["PVK_SBER_OD"]) if os.environ.get("PVK_SBER_OD") else mesic_zpet(do)
    return od, do


def sber(zdroje: list[str], od: date, do: date) -> int:
    nezname = [z for z in zdroje if z not in SBERACE]
    if nezname:
        print(f"neznámé zdroje: {', '.join(nezname)} (dostupné: {', '.join(SBERACE)})", file=sys.stderr)
        return 2
    nast = nastaveni()
    with pripoj(nast.database_url) as conn:
        zaregistruj_zdroje(conn)
        stahovac = Stahovac(conn, nast)
        stavy = [(z, *spust(conn, stahovac, SBERACE[z], od, do)) for z in zdroje]
        print(f"\nsběr za období {od} – {do} (bez posledního dne):")
        for zdroj, beh_id, stav in stavy:
            print(f"  {zdroj:<15} běh {beh_id:<6} {stav}")
        print("podrobnosti: make sber-stav")
    return 1 if any(stav == "chyba" for _z, _b, stav in stavy) else 0


CAS = ZoneInfo("Europe/Prague")


def _bunka(v, sirka: int) -> str:
    text = "" if v is None else (f"{v.astimezone(CAS):%Y-%m-%d %H:%M:%S}" if hasattr(v, "hour") else str(v))
    return (text[: sirka - 1] + "…") if len(text) > sirka else text.ljust(sirka)


def stav(pocet: int) -> int:
    nast = nastaveni()
    sloupce = [("id", "běh", 6), ("zdroj", "zdroj", 15), ("zacatek", "začátek (čas ČR)", 20), ("konec", "konec", 20),
               ("stav", "stav", 12), ("obdobi_od", "období od", 11), ("obdobi_do", "do", 11),
               ("pocet_zaznamu", "záznamů", 9), ("pocet_novych", "nových", 9), ("pocet_ve_zdroji", "ve zdroji", 10),
               ("pocet_chyb", "chyb", 5)]
    with pripoj(nast.database_url) as conn:
        posledni = conn.execute(
            "SELECT DISTINCT ON (zdroj) * FROM raw.beh_prehled ORDER BY zdroj, id DESC"
        ).fetchall()
        historie = conn.execute("SELECT * FROM raw.beh_prehled ORDER BY id DESC LIMIT %s", (pocet,)).fetchall()
    zahlavi = "".join(_bunka(popisek, sirka) for _n, popisek, sirka in sloupce)
    for titulek, radky in (("Poslední běh každého zdroje", posledni), (f"Posledních {pocet} běhů", historie)):
        print(f"\n{titulek}\n{zahlavi}\n{'-' * len(zahlavi)}")
        for r in radky:
            print("".join(_bunka(r[n], sirka) for n, _p, sirka in sloupce))
            if titulek.startswith("Poslední běh") and (r["chyby"] or r["poznamka"]):
                for chyba in (r["chyby"] or [])[:3]:
                    print(f"      chyba: {chyba[:160]}")
                if r["poznamka"]:
                    print(f"      pozn.: {r['poznamka'][:300]}")
    if not historie:
        print("zatím žádný běh (make sber)")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="pvk.sber", description="Sběr zdrojových dat do raw")
    p.add_argument("prikaz", nargs="?", default="sber", choices=["sber", "stav"])
    p.add_argument("--zdroje", default="", help="čárkami nebo mezerami oddělené kódy zdrojů (výchozí všechny)")
    p.add_argument("--od", type=date.fromisoformat)
    p.add_argument("--do", type=date.fromisoformat)
    p.add_argument("--pocet", type=int, default=20)
    a = p.parse_args(argv)
    if a.prikaz == "stav":
        return stav(a.pocet)
    od, do = vychozi_obdobi()
    od, do = a.od or od, a.do or do
    zdroje = [z for z in a.zdroje.replace(",", " ").split() if z] or list(SBERACE)
    return sber(zdroje, od, do)


if __name__ == "__main__":
    sys.exit(main())
