"""python -m pvk.pilot [vse|dostupnost|p1|p1meta|p2|p3|p4|report]

vse         stáhne vzorky do raw, změří P1–P4 a vytvoří docs/pilot_report.md + výjimky
dostupnost  jen test dostupnosti zdrojů
p1..p4      jednotlivá měření (P3 vyžaduje P1)
p1meta      přeměření P1 jen z metadat (větší vzorek, bez textu příloh)
report  jen přegeneruje report z uložených mezivýsledků (data/pilot/*.json)
"""

from __future__ import annotations

import logging
import sys
import time

from pvk.pilot.kontext import Kontext


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    prikaz = argv[0] if argv else "vse"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if prikaz not in {"vse", "dostupnost", "p1", "p1meta", "p2", "p3", "p4", "report"}:
        print(__doc__, file=sys.stderr)
        return 2
    ctx = Kontext.vytvor(offline=(prikaz == "report"))
    zacatek = time.monotonic()
    from pvk.pilot import dostupnost, p1, p2, p3, p4, report

    if prikaz in ("vse", "dostupnost"):
        dostupnost.over(ctx)
    if prikaz in ("vse", "p4"):
        p4.mer(ctx)
    if prikaz in ("vse", "p2"):
        p2.mer(ctx)
    if prikaz in ("vse", "p1"):
        p1.mer(ctx)
    if prikaz in ("vse", "p1meta"):
        p1.mer_metadata(ctx)
    if prikaz in ("vse", "p1", "p3"):
        p3.mer(ctx)
    if prikaz in ("vse", "report"):
        report.vytvor(ctx, trvani_s=time.monotonic() - zacatek)
    ctx.conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
