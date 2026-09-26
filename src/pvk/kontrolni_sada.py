"""Kontrolní sada k ručnímu potvrzení (docs/kontrolni_sada.csv): případy podle skupin metodiky z dostupných dat.

Každý řádek: skupina, údaj, odkaz na originál, návrh verdiktu, prázdný sloupec `potvrzeno` (vyplní člověk).
Výběr je deterministický (seřazení podle klíče, prvních N). Osobní údaje se neuvádějí (u fyzických osob jen
názvy vynechaných polí, D-009/D-035). Skupiny závislé na registru smluv mají stav „čeká na zdroj“.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import psycopg

from pvk.config import KOREN
from pvk.normalizace.zdroje import casti_zakazek

N = 5
SLOUPCE = ("skupina", "udaj", "odkaz_na_original", "navrh_verdiktu", "potvrzeno")
VVZ_WEB = "https://vvz.nipez.cz/vyhledat-formular/"


def _vvz_odkaz(conn: psycopg.Connection, formular: str) -> str:
    r = conn.execute("SELECT obsah->>'publicId' AS p FROM raw.zaznam WHERE zdroj = 'vvz' AND id_ve_zdroji = %s "
                     "ORDER BY id DESC LIMIT 1", (formular,)).fetchone()
    return VVZ_WEB + r["p"] if r and r["p"] else f"VVZ formulář {formular}"


def radky(conn: psycopg.Connection, kotva=None) -> list[dict]:
    out: list[dict] = []

    def pridej(skupina, udaj, odkaz, verdikt):
        out.append({"skupina": skupina, "udaj": udaj, "odkaz_na_original": odkaz, "navrh_verdiktu": verdikt,
                    "potvrzeno": ""})

    # 1. zakázky rozdělené na části (VVZ) -> tok za každou část
    casti = casti_zakazek(conn)
    for zakazka in sorted(casti)[:N]:
        f = conn.execute("SELECT id_ve_zdroji FROM raw.zaznam WHERE zdroj = 'vvz' AND obsah->'data'->>'evCisloZakazkyVvz' = %s "
                         "ORDER BY id_ve_zdroji LIMIT 1", (zakazka,)).fetchone()
        pridej("zakázka s částmi (VVZ)", f"{zakazka}: počet částí {len(casti[zakazka])} ({', '.join(casti[zakazka][:6])})",
               _vvz_odkaz(conn, f["id_ve_zdroji"]) if f else "",
               f"tok za každou část (vvz:{zakazka}:<část>, počet {len(casti[zakazka])}), tok celé zakázky ukončen (D-044)")
    # 2. zrušená řízení (VVZ) -> událost zrušení, nic se nepřepisuje
    for r in conn.execute("""SELECT DISTINCT ON (obsah->'data'->>'evCisloZakazkyVvz') id_ve_zdroji,
                                    obsah->'data'->>'evCisloZakazkyVvz' AS z, left(obsah->'data'->>'datumUverejneniVvz', 10) AS d
                               FROM raw.zaznam WHERE zdroj = 'vvz' AND (obsah->'data'->>'zakazkaZrusena')::boolean
                              ORDER BY obsah->'data'->>'evCisloZakazkyVvz', id_ve_zdroji LIMIT %s""", (N,)):
        pridej("zrušené řízení (VVZ)", f"{r['z']}, formulář {r['id_ve_zdroji']} ze dne {r['d']}", _vvz_odkaz(conn, r["id_ve_zdroji"]),
               "událost „zruseni“ u toku zakázky; tok ani částky se nepřepisují")
    # 3. dotace se stavem k datu (IS ReD)
    for r in conn.execute("""SELECT z.id_ve_zdroji, c.hodnota, c.stav_dat_k FROM core.castka c
                               JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = c.zdrojovy_zaznam_id
                              WHERE c.recorded_to = 'infinity' AND z.zdroj = 'red' ORDER BY z.id_ve_zdroji LIMIT %s""", (N,)):
        pridej("dotace se stavem k datu (IS ReD)", f"rozhodnutá částka {r['hodnota']} CZK, stav k {r['stav_dat_k']}",
               r["id_ve_zdroji"], f"dotace_priznana, mimo DPH, celkem; stav k datu exportu {r['stav_dat_k']} (D-039)")
    # 4. cizí měna -> kurz ČNB k datu uzavření, původní hodnota zůstává
    for r in conn.execute("""SELECT z.zdroj, z.id_ve_zdroji, c.typ, c.hodnota, c.mena, c.kurz_cnb, c.kurz_datum, c.hodnota_czk
                               FROM core.castka c JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = c.zdrojovy_zaznam_id
                              WHERE c.recorded_to = 'infinity' AND c.mena <> 'CZK' AND z.zdroj = 'vvz_detail'
                              ORDER BY c.mena, z.id_ve_zdroji LIMIT %s""", (N,)):
        pridej("cizí měna", f"{r['typ']} {r['hodnota']} {r['mena']} (formulář {r['id_ve_zdroji']})", _vvz_odkaz(conn, r["id_ve_zdroji"]),
               f"přepočet kurzem ČNB {r['kurz_cnb']} ze dne {r['kurz_datum']} = {r['hodnota_czk']} CZK; původní hodnota zůstává")
    # 5. subjekty po přeměně (kotva: ostatní skutečnosti v OR) -> nejsou nový subjekt
    if kotva is not None:
        nalezeno = 0
        kandidati = [r["ico"] for r in conn.execute("""SELECT DISTINCT s.ico FROM core.tok_aktualni t
                                   JOIN core.subjekt_aktualni s ON s.subjekt_id = t.prijemce_subjekt_id AND s.valid_to = 'infinity'
                                   JOIN core.tok_zdroj_aktualni tz ON tz.tok_id = t.tok_id
                                   JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = tz.zdrojovy_zaznam_id
                                  WHERE z.zdroj = 'vvz_detail' ORDER BY s.ico LIMIT 60""")]
        subjekty = kotva.subjekty_podle_ico(kandidati)
        for ico in kandidati:  # jen právnické osoby (fyzické osoby se nezobrazují, pravidlo 4)
            s = subjekty.get(ico)
            if nalezeno >= N or s is None or s.je_fyzicka_osoba is not False:
                continue
            if kotva.vznik_premenou(ico) is True:
                nalezeno += 1
                pridej("subjekt po přeměně (kotva/OR)", f"dodavatel IČO {ico} (právnická osoba)",
                       f"https://ares.gov.cz/ekonomicke-subjekty?ico={ico}",
                       "ostatní skutečnosti v OR uvádějí přeměnu -> indikátor nový subjekt ho nehodnotí (D-050)")
    # 6. fyzické osoby bez IČO -> osobní údaje vynechány, profil se nevytváří
    for r in conn.execute("""SELECT zdroj, id_ve_zdroji, url, redigovano FROM raw.zaznam
                              WHERE zdroj IN ('dotaceeu_2127', 'red') AND cardinality(redigovano) > 0
                              ORDER BY zdroj, id_ve_zdroji LIMIT %s""", (N,)):
        pridej("fyzická osoba nebo strana bez IČO", f"{r['zdroj']} {r['id_ve_zdroji']}: vynechána pole {', '.join(r['redigovano'])}",
               r["url"], "osobní údaje neuloženy (hash z původního záznamu); samostatný profil nevzniká (pravidlo 4)")
    # 7. skupiny závislé na registru smluv
    for skupina, verdikt in (
        ("párování smlouva–zakázka: doložená shoda", "čeká na zdroj (registr smluv; D-045, D-049)"),
        ("párování smlouva–zakázka: pravděpodobná shoda", "čeká na zdroj (registr smluv; váhy a práh neověřeny, D-049)"),
        ("dělení pod limit", "čeká na zdroj (registr smluv; D-050)"),
        ("smlouva v cizí měně / bez uvedené ceny (RS)", "čeká na zdroj (registr smluv)"),
        ("neplatná (nahrazená) verze záznamu RS", "čeká na zdroj (registr smluv)"),
    ):
        pridej(skupina, "–", "–", verdikt)
    return out


def zapis(radky_sady: list[dict], cesta: Path = KOREN / "docs" / "kontrolni_sada.csv") -> Path:
    with cesta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SLOUPCE)
        w.writeheader()
        w.writerows(radky_sady)
    return cesta


def main() -> int:
    from pvk.db import pripoj
    from pvk.kotva import vychozi_kotva

    with pripoj() as conn:
        r = radky(conn, vychozi_kotva())
    print(f"kontrolní sada: {len(r)} řádků -> {zapis(r)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
