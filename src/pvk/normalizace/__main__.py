"""make normalizace: raw -> core, limity ZZVZ do core.limit, měření do docs/blok3.md.

  python -m pvk.normalizace [--zdroje vvz,vvz_detail,dotaceeu_2127,red] [--bez-kotvy] [--bez-kurzu]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from pvk.config import KOREN, nastaveni
from pvk.db import pripoj
from pvk.http import Stahovac
from pvk.kotva import vychozi_kotva
from pvk.normalizace import Statistika, normalizuj
from pvk.normalizace.kurzy import KurzyCNB
from pvk.normalizace.zdroje import ADAPTERY
from pvk.zdroje import zaregistruj_zdroje

LIMITY = KOREN / "metodika" / "limity-zzvz-2026.09.json"
REPORT = KOREN / "docs" / "blok3.md"


def zapis_limity(conn, beh_id: int | None = None) -> int:
    """Limity VZMR a zákonné minimální lhůty (metodika/limity-zzvz-2026.09.json) do core.limit: jedna entita
    na kód limitu, hodnoty v čase jako verze s platností od–do (valid time). Entity dřívějšího klíčování
    (kód + datum, blok 3/1) se logicky ukončí (D-044, D-047)."""
    from pvk.core import klic_entity, zapis_entitu

    definice = json.loads(LIMITY.read_text(encoding="utf-8"))
    nove = set()
    for lim in definice["parametry"]["limity"]:
        data = {k: lim[k] for k in ("kod", "popis", "hodnota", "jednotka", "pravni_zaklad")}
        data["dph_rezim"] = lim.get("dph_rezim")
        do = date.fromisoformat(lim["platnost_do"]) if lim.get("platnost_do") else None
        nove.add(zapis_entitu(conn, "limit", lim["kod"], data, date.fromisoformat(lim["platnost_od"]), do))
    for r in conn.execute("SELECT DISTINCT limit_id, kod FROM core.limit WHERE recorded_to = 'infinity'").fetchall():
        if r["limit_id"] not in nove:
            conn.execute("SELECT core.ukonci_entitu('core.limit'::regclass, %s, %s, %s::uuid[], %s)",
                         (r["limit_id"], "limit překlíčován: jedna entita na kód, hodnoty jako verze v čase (D-047)",
                          [str(klic_entity("limit", r["kod"]))], beh_id))
    conn.commit()
    return len(definice["parametry"]["limity"])


class _BezKotvy:
    def subjekty_podle_ico(self, ica):
        return {}


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f} %" if b else "–"


def report(conn, stat: Statistika, pocet_limitu: int) -> str:
    r = ["# Blok 3 – normalizace a tok: měření", "",
         f"Stav k {date.today():%d. %m. %Y}. Vygenerováno `python -m pvk.normalizace` (make normalizace) nad vývojovými "
         "vzorky v raw; čísla popisují vzorek a běh normalizace, ne celé zdroje.", ""]
    r += ["## Vzorky v raw", "", "| zdroj | záznamů v raw | z toho vývojový vzorek | poslední běh sběru |", "|---|---:|---:|---|"]
    for x in conn.execute(
        """SELECT z.kod, count(r.id) n, count(r.id) FILTER (WHERE r.vyvojovy_vzorek) v,
                  (SELECT stav FROM raw.beh_prehled b WHERE b.zdroj = z.kod ORDER BY id DESC LIMIT 1) stav
             FROM raw.zdroj z LEFT JOIN raw.zaznam r ON r.zdroj = z.kod GROUP BY z.kod ORDER BY z.kod"""):
        if x["n"] or x["stav"]:
            r.append(f"| {x['kod']} | {x['n']} | {x['v']} | {x['stav'] or '–'} |")
    r += ["", "## Toky podle typu (aktuální verze v core)", "", "| zdroj | druh toku | toků | s určeným plátcem i příjemcem |",
          "|---|---|---:|---:|"]
    for x in conn.execute(
        """SELECT z.zdroj, t.druh, count(DISTINCT t.tok_id) n,
                  count(DISTINCT t.tok_id) FILTER (WHERE t.platce_subjekt_id IS NOT NULL AND t.prijemce_subjekt_id IS NOT NULL) oba
             FROM core.tok_aktualni t JOIN core.tok_zdroj_aktualni tz ON tz.tok_id = t.tok_id
             JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = tz.zdrojovy_zaznam_id
            GROUP BY 1, 2 ORDER BY 1, 2"""):
        r.append(f"| {x['zdroj']} | {x['druh']} | {x['n']} | {x['oba']} ({_pct(x['oba'], x['n'])}) |")
    celkem = conn.execute("SELECT druh, count(DISTINCT tok_id) n FROM core.tok_aktualni GROUP BY 1 ORDER BY 1").fetchall()
    r += ["", "Celkem: " + ", ".join(f"{x['druh']} {x['n']}" for x in celkem) + ".", ""]
    r += ["## Částky: podíl s určeným typem (cíl 100 %)", "",
          "Rámec: částky nalezené ve zdroji = částky zapsané v core (vždy s typem) + částky, které nešlo typovat "
          "(výjimky `castka_bez_meny`, `castka_bez_pravidla_metodiky`).", "",
          "| zdroj | částek ve zdroji | s typem, DPH, měnou a periodou | podíl |", "|---|---:|---:|---:|"]
    for x in conn.execute(
        """WITH s AS (SELECT z.zdroj, count(*) n FROM core.castka c
                        JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = c.zdrojovy_zaznam_id
                       WHERE c.recorded_to = 'infinity' GROUP BY 1),
                bez AS (SELECT zdroj, count(*) n FROM core.normalizace_vyjimka
                         WHERE druh IN ('castka_bez_meny', 'castka_bez_pravidla_metodiky') GROUP BY 1)
           SELECT coalesce(s.zdroj, bez.zdroj) zdroj, coalesce(s.n, 0) s_typem, coalesce(bez.n, 0) bez_typu
             FROM s FULL JOIN bez ON bez.zdroj = s.zdroj ORDER BY 1"""):
        n = x["s_typem"] + x["bez_typu"]
        r.append(f"| {x['zdroj']} | {n} | {x['s_typem']} | {_pct(x['s_typem'], n)} |")
    r += ["", "Částky v core podle typu (aktuální verze):", "", "| typ | měna | přepočet | počet |", "|---|---|---|---:|"]
    for x in conn.execute("SELECT typ, mena, coalesce(prepocet, 'neni_treba') prepocet, count(*) n FROM core.castka "
                          "WHERE recorded_to = 'infinity' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"):
        r.append(f"| {x['typ']} | {x['mena']} | {x['prepocet']} | {x['n']} |")
    bez_typu = conn.execute(
        "SELECT count(*) n FROM core.castka WHERE recorded_to = 'infinity' "
        "AND (typ IS NULL OR dph_rezim IS NULL OR perioda IS NULL OR mena IS NULL)"
    ).fetchone()["n"]
    r += ["", f"Částek v core bez typu, režimu DPH, měny nebo periody: {bez_typu} (databáze je nepřijme).", ""]
    r += ["## IČO: podíl nespárovaných podle zdroje", "",
          "Rámec: různé hodnoty IČO uvedené ve zdroji (tento běh). Nespárované = neplatné (formát, modulo 11) "
          "nebo nenalezené v kotvě (ARES).", "",
          "| zdroj | IČO ve zdroji | neplatná | nenalezená v kotvě | nespárovaná celkem | podíl |", "|---|---:|---:|---:|---:|---:|"]
    for zdroj in sorted(stat.ico_ve_zdroji):
        n = len(stat.ico_ve_zdroji[zdroj])
        nenalezena = {x["hodnota"] for x in conn.execute(
            "SELECT DISTINCT hodnota FROM core.normalizace_vyjimka WHERE zdroj = %s AND druh = 'ico_nenalezeno_v_kotve'",
            (zdroj,))}
        a, b = len(stat.ico_neplatna[zdroj]), len(nenalezena)
        r.append(f"| {zdroj} | {n} | {a} | {b} | {a + b} | {_pct(a + b, n)} |")
    r += ["", "## Výjimky", "", "| zdroj | druh výjimky | počet |", "|---|---|---:|"]
    vyjimky = conn.execute("SELECT zdroj, druh, count(*) n FROM core.normalizace_vyjimka GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
    for x in vyjimky:
        r.append(f"| {x['zdroj']} | {x['druh']} | {x['n']} |")
    r += ["", f"Výjimek celkem: {sum(x['n'] for x in vyjimky)} (tabulka `core.normalizace_vyjimka`).", ""]
    r += ["## Události", "", "| typ | počet |", "|---|---:|"]
    for x in conn.execute("SELECT typ, count(*) n FROM core.udalost_aktualni GROUP BY 1 ORDER BY 1"):
        r.append(f"| {x['typ']} | {x['n']} |")
    pokryti = conn.execute("SELECT zdroj, count(DISTINCT subjekt_id) n, min(zachycen_od) od FROM core.pokryti_platcu "
                           "GROUP BY 1 ORDER BY 1").fetchall()
    r += ["", "## Pokrytí zadavatelů a poskytovatelů (`core.pokryti_platcu`)", "",
          "| zdroj | plátců s IČO | nejstarší tok od |", "|---|---:|---|"]
    for x in pokryti:
        r.append(f"| {x['zdroj']} | {x['n']} | {x['od']} |")
    r += ["", f"## Limity\n\nV `core.limit` je {pocet_limitu} limitů (VZMR a minimální lhůty, "
          "zdroj u každého v `pravni_zaklad`, viz `metodika/limity-zzvz-2026.09.json`).", ""]
    if stat.poznamky:
        r += ["## Poznámky běhu", ""] + [f"* {p}" for p in stat.poznamky] + [""]
    return "\n".join(r)


def ramec_ico(conn, zdroje: list[str]) -> Statistika:
    """Rámec IČO podle zdroje z adaptérů (bez zápisu do core): různá IČO ve zdroji a neplatná."""
    from pvk.normalizace import METODIKA, over_ico

    stat = Statistika()
    parametry = json.loads(METODIKA.read_text(encoding="utf-8"))["parametry"]
    for zdroj in zdroje:
        for z in ADAPTERY[zdroj](conn, parametry, stat, True):
            for _pole, hodnota in z.ica:
                if hodnota in (None, ""):
                    continue
                ico, duvod = over_ico(hodnota)
                stat.ico_ve_zdroji[zdroj].add(ico or str(hodnota).strip())
                if duvod:
                    stat.ico_neplatna[zdroj].add(str(hodnota).strip())
    return stat


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="pvk.normalizace")
    p.add_argument("--zdroje", default=",".join(ADAPTERY))
    p.add_argument("--bez-kotvy", action="store_true", help="neověřovat neznámá IČO v kotvě (vše = nenalezeno)")
    p.add_argument("--bez-kurzu", action="store_true", help="kurzy ČNB nestahovat (cizí měna s příznakem)")
    p.add_argument("--report", default=str(REPORT))
    p.add_argument("--jen-report", action="store_true", help="jen měření nad core (bez normalizace)")
    a = p.parse_args(argv)
    nast = nastaveni()
    zdroje = [z for z in a.zdroje.replace(",", " ").split() if z]
    if a.jen_report:
        with pripoj(nast.database_url) as conn:
            pocet = conn.execute("SELECT count(*) n FROM core.limit WHERE recorded_to = 'infinity'").fetchone()["n"]
            text = report(conn, ramec_ico(conn, zdroje), pocet)
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"měření v {a.report}")
        return 0
    with pripoj(nast.database_url) as conn:
        zaregistruj_zdroje(conn)
        kurzy = None if a.bez_kurzu else KurzyCNB(Stahovac(conn, nast))
        kotva = _BezKotvy() if a.bez_kotvy else vychozi_kotva()
        stat = normalizuj(conn, zdroje, kotva, kurzy)
        if a.bez_kurzu:
            stat.poznamky.append("kurzy ČNB se nestahovaly: cizoměnové částky nepřepočteny (kurz_nedostupny)")
        pocet = zapis_limity(conn)
        ramec = ramec_ico(conn, zdroje)
        ramec.poznamky = stat.poznamky
        text = report(conn, ramec, pocet)
    with open(a.report, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"normalizace hotova, měření v {a.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
