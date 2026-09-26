"""Souhrnný objem subjektu v rámci jednoho zdroje a jednoho typu částky (D-026, D-046).

Souhrn nese vždy pokrytí (kolik toků subjektu ve zdroji má částku daného typu a kolik má IČO obou stran)
a podíl objemu, který stojí na heuristické deduplikaci (částky zdrojových záznamů navázaných na tok jen
pravděpodobnou vazbou). Nad zveřejněným prahem (metodika `souhrny-2026.09`) vrací rozpětí: dolní mez se
shodou (pravděpodobné duplicity odečtené), horní mez bez ní (vše sečteno). Sčítá se jen přes core.soucet()
(různé typy, měny, režimy DPH a periody sečíst nejde – PV003).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg

from pvk.config import KOREN

METODIKA = KOREN / "metodika" / "souhrny-2026.09.json"
ZDROJE = {"vvz": ("vvz", "vvz_detail"), "dotaceeu_2127": ("dotaceeu_2127",), "red": ("red",),
          "registr_smluv": ("registr_smluv",)}
DOTACNI = {"dotace_priznana", "dotace_cerpana", "vratka"}


def parametry(cesta: Path = METODIKA) -> dict:
    return json.loads(cesta.read_text(encoding="utf-8"))


def souhrn_subjektu(conn: psycopg.Connection, ico: str, zdroj: str, typ: str, obdobi_od: date, obdobi_do: date, *,
                    role: str = "prijemce", mena: str = "CZK", dph_rezim: str | None = None,
                    perioda: str = "celkem") -> dict:
    """Souhrnný objem subjektu (IČO) v roli plátce/příjemce za období v jednom zdroji a typu částky."""
    if role not in ("platce", "prijemce"):
        raise ValueError("role je platce nebo prijemce")
    if zdroj not in ZDROJE:
        raise ValueError(f"neznámý zdroj souhrnu: {zdroj}")
    definice = parametry()
    p = definice["parametry"]
    dph = dph_rezim or ("mimo_dph" if typ in DOTACNI else "bez_dph")
    r = conn.execute(
        f"""
        WITH s AS (SELECT subjekt_id FROM core.subjekt_aktualni WHERE ico = %(ico)s AND valid_to = 'infinity'),
        t AS (
          SELECT DISTINCT tk.tok_id, tk.platce_subjekt_id IS NOT NULL AND tk.prijemce_subjekt_id IS NOT NULL AS obe
            FROM core.tok_aktualni tk
            JOIN core.tok_zdroj_aktualni tz ON tz.tok_id = tk.tok_id
            JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = tz.zdrojovy_zaznam_id
           WHERE z.zdroj = ANY(%(zdroje)s) AND tk.{role}_subjekt_id IN (SELECT subjekt_id FROM s)
             AND tk.valid_from < %(do)s AND tk.valid_to > %(od)s
        ),
        c AS (
          SELECT c.tok_id, c.stav_dat_k, ROW(c.typ, c.mena, c.dph_rezim, c.perioda, c.hodnota)::core.typovana_castka AS tc,
                 EXISTS (SELECT 1 FROM core.tok_zdroj_aktualni h WHERE h.tok_id = c.tok_id
                            AND h.zdrojovy_zaznam_id = c.zdrojovy_zaznam_id AND h.stav = 'pravdepodobna') AS heur
            FROM core.castka c JOIN t ON t.tok_id = c.tok_id
           WHERE c.recorded_to = 'infinity' AND c.typ = %(typ)s AND c.mena = %(mena)s AND c.dph_rezim = %(dph)s
             AND c.perioda = %(perioda)s AND c.valid_from >= %(od)s AND c.valid_from < %(do)s
        )
        SELECT (SELECT count(*) FROM t) AS toku,
               (SELECT count(*) FROM t WHERE obe) AS toku_obe_strany,
               (SELECT count(DISTINCT tok_id) FROM c) AS toku_s_castkou,
               (SELECT count(*) FROM c) AS pocet_castek,
               (SELECT (core.soucet(tc)).hodnota FROM c) AS celkem,
               (SELECT (core.soucet(tc)).hodnota FROM c WHERE heur) AS heuristicky,
               (SELECT min(stav_dat_k) FROM c) AS stav_dat_k
        """,
        {"ico": ico, "zdroje": list(ZDROJE[zdroj]), "od": obdobi_od, "do": obdobi_do, "typ": typ, "mena": mena,
         "dph": dph, "perioda": perioda},
    ).fetchone()
    celkem = r["celkem"] or Decimal(0)
    heur = r["heuristicky"] or Decimal(0)
    podil = float(heur / celkem) if celkem else 0.0
    vysledek = {
        "druh": "souhrn",
        "kod": f"objem_{role}",
        "ico": ico,
        "zdroj": zdroj,
        "typ": typ,
        "mena": mena,
        "dph_rezim": dph,
        "perioda": perioda,
        "obdobi_od": obdobi_od.isoformat(),
        "obdobi_do": obdobi_do.isoformat(),
        "pocet_castek": r["pocet_castek"],
        "hodnota": str(celkem - heur),  # se shodou: pravděpodobné duplicity odečtené
        "pokryti": {"toku": r["toku"], "s_castkou_typu": r["toku_s_castkou"], "s_ico_obou_stran": r["toku_obe_strany"]},
        "podil_heuristicke_deduplikace": round(podil, 4),
        "rozpeti": None,
        "metodika_verze": definice["kod"],
    }
    if podil > float(p["prah_podilu_heuristiky_pro_rozpeti"]):
        vysledek["rozpeti"] = {"dolni_se_shodou": str(celkem - heur), "horni_bez_shody": str(celkem)}
    if typ in DOTACNI or zdroj in ("red", "dotaceeu_2127"):
        vysledek["stav_k_datu"] = r["stav_dat_k"].isoformat() if r["stav_dat_k"] else None
    return vysledek
