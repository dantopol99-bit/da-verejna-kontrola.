"""Test dostupnosti zdokumentovaných endpointů (jeden pokus bez opakování, zapisuje se do raw.stazeni).

Slouží jako doklad v reportu: co bylo v okamžiku pilotu z prostředí dosažitelné a co ne.
"""

from __future__ import annotations

from pvk.pilot.kontext import LOG, Kontext
from pvk.zdroje.dotace import je_antibot_vyzva

ENDPOINTY = [
    ("registr_smluv", "https://data.smlouvy.gov.cz/index.xml", "RS – index dumpů (otevřená data)"),
    ("registr_smluv", "https://smlouvy.gov.cz/", "RS – web a přílohy smluv"),
    ("hlidac_statu_rs", "https://www.hlidacstatu.cz/Detail/39673953", "Hlídač státu – zrcadlo RS"),
    ("vvz", "https://api.vvz.nipez.cz/api/submissions/search?formGroup=vz&form=vz&page=1&limit=1", "VVZ – API"),
    ("isvz", "https://isvz.nipez.cz/opendata", "ISVZ – otevřená data VZ"),
    ("nen", "https://nen.nipez.cz/", "NEN"),
    ("red", "https://red.fs.gov.cz/opendata/api/3/action/package_list", "IS ReD – katalog otevřených dat"),
    ("cedr", "https://cedropendata.mfcr.cz/c3lod/cedr/", "CEDR III (historické)"),
    ("dotaceeu_2127", "https://www.dotaceeu.cz/cs/statistiky-a-analyzy/seznam-operaci-(prijemcu)", "Seznam operací 21+"),
    ("szif", "https://szif.gov.cz/cs/seznam-prijemcu-dotaci", "SZIF – seznam příjemců"),
]


def over(ctx: Kontext) -> list[dict]:
    vysledky = []
    for zdroj, url, popis in ENDPOINTY:
        odp = ctx.stahovac.ziskej(zdroj, url, obnov=True, pokusy=0, timeout=(15, 40))
        stav = "dostupne" if odp.status == 200 else "nedostupne"
        if odp.status == 200 and odp.cesta is not None and je_antibot_vyzva(odp.obsah()):
            stav = "antibot_vyzva"
        vysledky.append({"zdroj": zdroj, "url": url, "popis": popis, "cas": odp.cas_stazeni, "http_status": odp.status,
                         "chyba": (odp.chyba or "")[:200] or None, "stav": stav, "stazeni_id": odp.stazeni_id})
        LOG.info("dostupnost %-16s %-12s %s", zdroj, stav, url)
    ctx.uloz("dostupnost", vysledky)
    return vysledky
