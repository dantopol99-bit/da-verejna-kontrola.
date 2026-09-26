"""Zdroje dat platformy a jejich evidence v raw.zdroj. Podrobnosti v docs/sources.md."""

from __future__ import annotations

import psycopg

from pvk import raw

ZDROJE: dict[str, dict[str, str]] = {
    "registr_smluv": {
        "nazev": "Registr smluv – otevřená data (XML dumpy)",
        "spravce": "Digitální a informační agentura",
        "url": "https://data.smlouvy.gov.cz/",
        "licence": "otevřená data podle zákona č. 340/2015 Sb.",
    },
    "hlidac_statu_rs": {
        "nazev": "Hlídač státu – zrcadlo registru smluv (metadata a kopie příloh)",
        "spravce": "Hlídač státu z. ú.",
        "url": "https://www.hlidacstatu.cz/",
        "licence": "CC BY 3.0 CZ",
        "poznamka": "Použije se jen při nedostupnosti oficiálního zdroje; kopie příloh se ověřují hashem z metadat RS.",
    },
    "vvz": {
        "nazev": "Věstník veřejných zakázek (veřejné API webu VVZ)",
        "spravce": "Ministerstvo pro místní rozvoj",
        "url": "https://api.vvz.nipez.cz/",
        "licence": "veřejné údaje podle zákona č. 134/2016 Sb.",
    },
    "vvz_detail": {
        "nazev": "Věstník veřejných zakázek – detail formulářů eForms (veřejné API webu VVZ)",
        "spravce": "Ministerstvo pro místní rozvoj",
        "url": "https://api.vvz.nipez.cz/api/submissions/children/search",
        "licence": "veřejné údaje podle zákona č. 134/2016 Sb.",
        "poznamka": "Úplný obsah formuláře k souhrnu ze zdroje vvz (stejné evidenční číslo formuláře).",
    },
    "isvz": {
        "nazev": "ISVZ – otevřená data o veřejných zakázkách",
        "spravce": "Ministerstvo pro místní rozvoj",
        "url": "https://isvz.nipez.cz/opendata",
        "licence": "otevřená data",
    },
    "nen": {
        "nazev": "Národní elektronický nástroj (NEN)",
        "spravce": "Ministerstvo pro místní rozvoj",
        "url": "https://nen.nipez.cz/",
        "licence": "veřejné údaje podle zákona č. 134/2016 Sb.",
    },
    "cedr": {
        "nazev": "CEDR III – otevřená data (historické, nahrazeno IS ReD)",
        "spravce": "Ministerstvo financí",
        "url": "https://cedropendata.mfcr.cz/c3lod/cedr/",
        "licence": "otevřená data",
    },
    "red": {
        "nazev": "IS ReD – Registr dotací, otevřená data",
        "spravce": "Generální finanční ředitelství / Ministerstvo financí",
        "url": "https://red.fs.gov.cz/opendata/",
        "licence": "otevřená data",
    },
    "dotaceeu_2127": {
        "nazev": "Seznam operací (příjemců) 2021–2027",
        "spravce": "Ministerstvo pro místní rozvoj – Národní orgán pro koordinaci",
        "url": "https://www.dotaceeu.cz/cs/statistiky-a-analyzy/seznam-operaci-(prijemcu)",
        "licence": "zveřejňováno podle čl. 49 nařízení (EU) 2021/1060",
    },
    "szif": {
        "nazev": "SZIF – seznam příjemců dotací z fondů EU",
        "spravce": "Státní zemědělský intervenční fond",
        "url": "https://szif.gov.cz/cs/seznam-prijemcu-dotaci",
        "licence": "zveřejňováno podle čl. 98 nařízení (EU) 2021/2116",
    },
}


def zaregistruj_zdroje(conn: psycopg.Connection) -> None:
    for kod, z in ZDROJE.items():
        raw.zajisti_zdroj(conn, kod, z["nazev"], z["spravce"], z["url"], z.get("licence"), z.get("poznamka"))
    conn.commit()
