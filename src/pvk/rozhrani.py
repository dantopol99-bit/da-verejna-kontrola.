"""Rozhraní pro kotvu: záložka „Veřejné peníze“ v profilu firmy (specifikace docs/rozhrani_kotva.md).

`verejne_penize(conn, ico, k_datu)` vrací pro jedno IČO JSON-serializovatelný slovník podle schématu
`pvk.verejne_penize` verze SCHEMA_VERZE. Kotva výstup jen zobrazuje; do repozitáře kotvy se nezasahuje.
Ven jde jen to, co projde publikační bránou (pvk.publikace): souhrny v rámci jednoho zdroje a typu částky
s pokrytím a podílem heuristiky, publikovatelné výsledky indikátorů bez prahů (D-052), žádné párování (D-049).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import psycopg

from pvk import publikace
from pvk.souhrny import souhrn_subjektu

SCHEMA = "pvk.verejne_penize"
SCHEMA_VERZE = "1.0"
OKNO_LET = 3
# (sekce, role subjektu, zdroj souhrnu, typ částky)
SOUHRNY = (
    ("zakazky_jako_zadavatel", "platce", "vvz", "vysoutezena"),
    ("zakazky_jako_zadavatel", "platce", "vvz", "predpokladana"),
    ("zakazky_jako_dodavatel", "prijemce", "vvz", "vysoutezena"),
    ("zakazky_jako_zadavatel", "platce", "dotaceeu_2127", "smluvni"),
    ("zakazky_jako_dodavatel", "prijemce", "dotaceeu_2127", "smluvni"),
    ("dotace", "prijemce", "dotaceeu_2127", "dotace_priznana"),
    ("dotace", "prijemce", "dotaceeu_2127", "dotace_cerpana"),
    ("dotace", "prijemce", "red", "dotace_priznana"),
)
UPOZORNENI = [
    "Indikátor je signál k prověření, nikdy zjištění.",
    "Souhrny platí vždy v rámci jednoho zdroje a jednoho typu částky; napříč zdroji ani typy se nesčítá.",
    "Chybějící údaj ve zdroji není nulová hodnota; dotační údaje nesou stav k datu zdroje.",
    "Registr smluv zatím není zahrnut (zdroj z cloudu nedostupný); párování smlouva–zakázka se nezobrazuje.",
]


def verejne_penize(conn: psycopg.Connection, ico: str, k_datu: date | None = None, kotva=None) -> dict:
    """Výstup záložky „Veřejné peníze“ pro jedno IČO k datu (valid time), podle dnešního poznání (transaction time)."""
    k_datu = k_datu or date.today()
    zaklad = {"schema": SCHEMA, "schema_verze": SCHEMA_VERZE, "ico": ico, "k_datu": k_datu.isoformat(),
              "stav_poznani": datetime.now(UTC).isoformat(timespec="seconds")}
    if kotva is not None:
        s = kotva.subjekt_podle_ico(ico)
        if s is not None and s.je_fyzicka_osoba is not False:
            return {**zaklad, "vydano": False, "duvod": "fyzická osoba nebo neurčená právní forma – profil se nevydává"}
    subjekt = conn.execute("SELECT subjekt_id FROM core.subjekt_aktualni WHERE ico = %s AND valid_to = 'infinity'",
                           (ico,)).fetchone()
    if subjekt is None:
        return {**zaklad, "vydano": False, "duvod": "IČO v datech platformy nenalezeno (není to nulová hodnota)"}
    od = date(k_datu.year - OKNO_LET, k_datu.month, 1)
    do = k_datu + timedelta(days=1)
    metodiky = publikace.nacti_metodiky()
    vystup = {**zaklad, "vydano": True, "obdobi_od": od.isoformat(), "obdobi_do": do.isoformat(),
              "zakazky_jako_zadavatel": [], "zakazky_jako_dodavatel": [], "dotace": [], "indikatory": [],
              "vynechano": [], "upozorneni": UPOZORNENI}
    for sekce, role, zdroj, typ in SOUHRNY:
        s = souhrn_subjektu(conn, ico, zdroj, typ, od, do, role=role)
        if s["pocet_castek"] == 0:
            continue  # bez částek daného typu se souhrn nevydává (chybějící údaj není nula)
        poruseni = publikace.over_vystup(s, metodiky, f"{sekce}/{zdroj}/{typ}")
        if poruseni:
            vystup["vynechano"].append({"polozka": f"{sekce}/{zdroj}/{typ}", "duvod": sorted({p.kod for p in poruseni})})
            continue
        vystup[sekce].append({k: s[k] for k in ("zdroj", "typ", "mena", "dph_rezim", "perioda", "hodnota", "pocet_castek",
                                                "pokryti", "podil_heuristicke_deduplikace", "rozpeti", "metodika_verze")}
                             | ({"stav_k_datu": s.get("stav_k_datu")} if "stav_k_datu" in s else {}))
    for r in conn.execute(
        """SELECT v.indikator_kod, v.obdobi_od, v.obdobi_do, v.pocet_pripadu, v.zaklad, v.hodnota, v.srovnavaci_skupina,
                  v.text, v.typ_castky, v.stav_dat_k, m.kod AS metodika_verze
             FROM ind.indikator_k_publikaci v
             JOIN core.metodika_verze m ON m.metodika_verze_id = v.metodika_verze_id AND m.recorded_to = 'infinity'
                  AND m.valid_to = 'infinity'
            WHERE v.subjekt_id = %s AND v.obdobi_od <= %s ORDER BY v.indikator_kod, v.obdobi_od DESC""",
        (subjekt["subjekt_id"], k_datu)):
        polozka = {"druh": "indikator", "indikator_kod": r["indikator_kod"], "obdobi_od": r["obdobi_od"].isoformat(),
                   "obdobi_do": r["obdobi_do"].isoformat(), "pocet_pripadu": r["pocet_pripadu"],
                   "zaklad": str(r["zaklad"]), "hodnota": str(r["hodnota"]), "srovnavaci_skupina": r["srovnavaci_skupina"],
                   "metodika_verze": r["metodika_verze"], "text": r["text"], "typ_castky": r["typ_castky"]}
        if r["stav_dat_k"]:
            polozka["stav_k_datu"] = r["stav_dat_k"].isoformat()
        poruseni = publikace.over_vystup(polozka, metodiky, r["indikator_kod"])
        if poruseni:
            vystup["vynechano"].append({"polozka": r["indikator_kod"], "duvod": sorted({p.kod for p in poruseni})})
            continue
        vystup["indikatory"].append(polozka)
    return vystup


def main(argv: list[str] | None = None) -> int:
    import sys

    from pvk.db import pripoj

    argv = argv if argv is not None else sys.argv[1:]
    with pripoj() as conn:
        print(json.dumps(verejne_penize(conn, argv[0], date.fromisoformat(argv[1]) if len(argv) > 1 else None),
                         ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
