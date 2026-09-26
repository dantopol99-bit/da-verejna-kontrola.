# Zdroje dat – aktuální endpointy otevřených dat

Stav ověřen 25. 9. 2026 (webové vyhledávání, Národní katalog otevřených dat – SPARQL `https://data.gov.cz/sparql`,
a přímé dotazy z prostředí pilotu). Dostupnost z prostředí pilotu je doložena v `raw.stazeni`
(test `pvk.pilot.dostupnost`, spouští se v `make pilot`) a shrnuta v [pilot_report.md](pilot_report.md).

Sběr do raw (blok 2): `make sber`, přehled běhů `make sber-stav` – viz [oddíl 8](#8-sběr-do-raw-blok-2--dostupnost-a-ověřovací-běh).

Legenda dostupnosti z prostředí pilotu: ✅ dostupné · ⛔ nedostupné (spojení ukončeno / odmítnuto) ·
🛡 anti-bot výzva (neobcházíme).

---

## 1. Registr smluv (ISRS)

| | |
|---|---|
| Správce | Digitální a informační agentura (DIA; dříve MV ČR) |
| Zákon | 340/2015 Sb., o registru smluv |
| Web | `https://smlouvy.gov.cz/` – detail verze záznamu `https://smlouvy.gov.cz/smlouva/{idVerze}`, soubor přílohy `https://smlouvy.gov.cz/smlouva/soubor/{idPrilohy}/{nazev}` |
| Otevřená data | `https://data.smlouvy.gov.cz/` |
| Index dumpů | `https://data.smlouvy.gov.cz/index.xml` (seznam dumpů s hashem, velikostí, časem generování, příznakem dokončeného měsíce) |
| Měsíční dump | `https://data.smlouvy.gov.cz/dump_RRRR_MM.xml` |
| Denní dump | `https://data.smlouvy.gov.cz/dump_RRRR_MM_DD.xml` |
| Formát | XML podle XSD ISRS; kořen `<dump>` s metadaty dumpu, pak sekvence `<zaznam>` (verze záznamů smluv): `identifikator/idSmlouvy, idVerze`, `odkaz`, `casZverejneni`, `smlouva/subjekt` (publikující strana: `datovaSchranka, nazev, ico, adresa, utvar, platce`), `smlouva/smluvniStrana` 1..n (`… prijemce`), `predmet`, `datumUzavreni`, `cisloSmlouvy`, `schvalil`, `hodnotaBezDph`, `hodnotaVcetneDph`, `ciziMena/hodnota, mena`, `navazanyZaznam`, `prilohy/priloha` (`nazevSouboru`, `hash algoritmus="sha256"`, `odkaz`), `platnyZaznam` |
| Aktualizace | průběžně; **dumpy se zpětně přepisují** (změna nebo znepřístupnění záznamu se promítne i do starších dumpů) – proto ukládáme hash staženého dumpu a vybrané záznamy do `raw` |
| API pro zveřejňující | ISRS (SOAP) – jen pro zápis, vyhledávací API pro veřejnost neexistuje |
| NKOD | datová sada „Smlouvy v Registru smluv“ (poskytovatel DIA, distribuce `https://data.smlouvy.gov.cz/`) |
| Dostupnost z pilotu | ⛔ `data.smlouvy.gov.cz` i `smlouvy.gov.cz`: TLS spojení ukončeno bez odpovědi (≈ 12 s). Podle monitoringu Hlídače státu (https://www.hlidacstatu.cz/statniweby/info/128, stav k 25. 9. 2026) byl registr v týdnu 18.–25. 9. 2026 nedostupný 58,6 % času i z ČR (nejdelší výpadek 14 min) – jde o kombinaci přetížení/ochrany a omezení pro zahraniční sítě. |
| V pilotu | kód připraven (`pvk.zdroje.registr_smluv`: proudový parser dumpů, výběr z denních dumpů); při nedostupnosti se použije zrcadlo (níže) |

### 1a. Zrcadlo registru smluv – Hlídač státu

| | |
|---|---|
| Správce | Hlídač státu z. ú. |
| Licence | CC BY 3.0 CZ (povinné uvedení zdroje); `robots.txt` stránky detailu a vyhledávání nezakazuje |
| Detail záznamu | `https://www.hlidacstatu.cz/Detail/{idVerze}` (metadata RS; částky zaokrouhlené na celé Kč) |
| Kopie přílohy | `https://www.hlidacstatu.cz/KopiePrilohy/{idVerze}?hash={sha256}` – parametr `hash` = hash přílohy z metadat RS; kopii přijímáme jen při shodě SHA-256 staženého souboru |
| Vyhledávání | `https://www.hlidacstatu.cz/HledatSmlouvy?Q=…&page=N` (30 výsledků na stranu); dotazy `ico:X AND ico:Y`, `podepsano:[RRRR-MM-DD TO RRRR-MM-DD]`, `zverejneno:[…]`, fráze v uvozovkách (i v textu příloh) |
| API | `https://api.hlidacstatu.cz/api/v2/…` – vyžaduje registraci a token (nepoužito) |
| Dostupnost z pilotu | ✅ |
| Nepoužíváme | K-Index, „angažovanost politicky aktivních osob“, sponzoring a další odvozené údaje Hlídače (pravidla 5 a 6) |

## 2. Věstník veřejných zakázek (VVZ)

| | |
|---|---|
| Správce | Ministerstvo pro místní rozvoj |
| Web | `https://vvz.nipez.cz/` (od 2023; původní doména `vestnikverejnychzakazek.cz` dnes vrací cizí certifikát – nepoužívat) |
| API webu (bez přihlášení) | `https://api.vvz.nipez.cz/api/submissions/search` – filtry `formGroup=vz&form=vz`, `workflowPlace=UVEREJNENO_VVZ`, `data.druhFormulare[]=29…`, `data.datumUverejneniVvz[gte]/[lt]`, řazení `order[variableId]=asc`, stránkování `page`, `limit`; počet v hlavičce `X-Total-Count` (max. 50 000 položek na dotaz) |
| Obsah formuláře | `https://api.vvz.nipez.cz/api/submissions/children/search?submission={id}` – strom eForms `ND-Root` s poli BT-* (BT-501 IČO, BT-27 předpokládaná hodnota, BT-720 hodnota nabídky, BT-145 datum uzavření smlouvy, BT-150 ID smlouvy, **BT-151 URL smlouvy – často přímo odkaz do registru smluv**) |
| Veřejný detail | `https://api.vvz.nipez.cz/api/submissions/public/{publicId}`; stránka `https://vvz.nipez.cz/vyhledat-formular/{publicId}` |
| Formuláře výsledku | eForms 29 (obecná), 30 (sektorová), 31 (obrana), 32 (koncese), 33–35 (zjednodušený režim), 36–37 soutěž o návrh; 38–40, E6 změny závazku |
| Rozsah | ve sledovaném období 1. 9. 2025 – 31. 8. 2026: 69 837 uveřejnění, z toho 35 786 oznámení o výsledku (29–35) |
| Poznámka | API je veřejný backend webu, není formálně dokumentováno jako otevřená data. Používáme šetrně (≥ 0,35 s mezi dotazy, cache). |
| Dostupnost z pilotu | ✅ |

## 3. NEN a otevřená data ISVZ

| | |
|---|---|
| NEN | `https://nen.nipez.cz/` (MMR). Veřejné API NEN slouží nákupům z e-katalogů, ne otevřeným datům. Profily zadavatelů v NEN publikují strukturovaná data podle přílohy 3 vyhlášky 345/2023 Sb. |
| ISVZ – otevřená data | `https://isvz.nipez.cz/opendata`: „původní“ Open Data (do 1/2024, XML) a „nová“ Open Data z Registru veřejných zakázek (od 2/2024; zdroje VVZ, NEN, Tender Arena, TENDERMARKET), měsíčně, XML/JSON. Nápověda: `https://skd.nipez.cz/ISVZ/MetodickaPodpora/Napovedaopendata.pdf` |
| NKOD | „Data z NIPEZ“ je v katalogu jen jako návrh k otevření (příslib, plán 9/2024) |
| Dostupnost z pilotu | ⛔ `nen.nipez.cz`, `isvz.nipez.cz`, `nen-ref.nipez.cz`: spojení ukončeno bez odpovědi |
| V pilotu | nahrazeno VVZ (oznámení z NEN se do VVZ odesílají) |

## 4. Dotace – CEDR / IS ReD

| | |
|---|---|
| CEDR III | `https://cedropendata.mfcr.cz/c3lod/cedr/` – historické LOD/CSV; ⛔ (brána odmítá spojení) – nahrazeno IS ReD |
| IS ReD – otevřená data | Generální finanční ředitelství / MF; katalog CKAN `https://red.fs.gov.cz/opendata/` (dříve `red.financnisprava.cz`), API `https://red.fs.gov.cz/opendata/api/3/action/package_show?id={balicek}` |
| Hlavní tabulky (CSV.gz, UTF-8) | `prijemce-pomoci` → `prijemce.csv.gz` (≈ 67 MB, 1,1 mil. řádků: `iriPrijemce, ico, obchodniNazev, jmeno, prijmeni, rokNarozeni, iriPravniForma, iriStat…`), `dotace` → `dotace.csv.gz` (≈ 272 MB, 2,35 mil.: `iriDotace, iriPrijemce, kod, identifikator, nazev, podpisDatum…`), `rozhodnuti` (≈ 273 MB), `rozpoctove-obdobi` (≈ 296 MB), číselníky (`pravni-forma`, `poskytovatel-dotace`, `operacni-program`…) a RDF (N3) varianty |
| Aktualizace | export k 21. 2. 2026 (soubory upraveny 24. 3. 2026) – data mají zpoždění |
| TLS | server neposílá mezilehlý certifikát Thawte TLS RSA CA G1 → doplněn v `certs/extra-intermediates.pem` |
| Dostupnost z pilotu | ✅ |
| Katalog MF | `https://data.mf.gov.cz/` (přehled datových sad ReD) |

## 5. Příjemci EU fondů

| | |
|---|---|
| Seznam operací 2021–2027 | MMR – NOK, `https://www.dotaceeu.cz/cs/statistiky-a-analyzy/seznam-operaci-(prijemcu)`; měsíční XLSX „Seznam operací 21+ (List of Operations)“ (≈ 16 MB, ≈ 48 700 řádků: program, projekt, **příjemce – název, IČ, právní forma**, částky, a také zakázky v projektech s IČ dodavatelů); poslední soubor k 1. 9. 2026 |
| Seznam operací FN | tamtéž, finanční nástroje |
| 2014–2020 | archivní seznamy operací na dotaceeu.cz a NKOD („Seznam příjemců dotací z fondů EU za rok …“) |
| Dostupnost z pilotu | ✅ |
| SZIF (EZZF/EZFRV) | `https://szif.gov.cz/cs/seznam-prijemcu-dotaci`; otevřená data `https://szif.gov.cz/cs/CmOpendata?rid=/apa_anon/cs/dokumenty_ke_stazeni/pkp/spd/opendata/spd{RRRR}czk.csv` (EU fondy, v Kč) a `…/spdnd/opendata/spdnd{RRRR}.csv` (národní zdroje); v NKOD roky 2017–2025 |
| Dostupnost z pilotu | 🛡 server vrací JavaScriptovou výzvu F5 (TSPD) místo dat i pro soubory otevřených dat – neobcházíme; nutné ověřit z české sítě / požádat SZIF o přímý přístup |

## 6. ARES (kotva v pilotu)

| | |
|---|---|
| Správce | Ministerstvo financí |
| REST API | `https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}` (GET), vyhledávání `…/ekonomicke-subjekty/vyhledat` (POST JSON `obchodniJmeno`, `start`, `pocet`); dokumentace `https://ares.gov.cz/swagger-ui/` |
| Použití | jen `pvk.kotva.AresKotva.subjekt_podle_ico()`; výsledky se neukládají (žádná lokální kopie registru subjektů) |
| Dostupnost z pilotu | ✅ |

## 7. Nepoužívané zdroje (pravidla)

* **Evidence skutečných majitelů** – uzavřena od 17. 12. 2025; vlastnictví jen do úrovně obchodního rejstříku.
* **Centrální registr oznámení** (majetková přiznání) – nepoužívá se vůbec.
* Odvozené údaje třetích stran o politických vazbách osob – ve v1 žádné vazby osoba → politik.

## 8. Sběr do raw (blok 2) – dostupnost a ověřovací běh

Dostupnost ověřena **26. 9. 2026 12:27–12:29 SELČ jedním pokusem bez opakování** přímo v ověřovacím
běhu `make sber` (pokus je v `raw.stazeni` s `beh_id`, výsledek v `raw.beh_prehled`). Blokované zdroje
odmítají spojení z cloudových adres (server ukončí TLS spojení bez odpovědi); **stahovače poběží beze
změny kódu z české sítě** – stačí `make sber` (nebo `make sber ZDROJE="registr_smluv nen isvz cedr"`).

| Zdroj (`raw.zdroj`) | Test dostupnosti | Výsledek z cloudu | Stahovač (`pvk.sber.sberace`) |
|---|---|---|---|
| `registr_smluv` | `https://data.smlouvy.gov.cz/index.xml` | ⛔ `ConnectionError … Connection aborted` | denní dumpy `dump_RRRR_MM_DD.xml` za období, záznam = `<zaznam>` (ID = idVerze) |
| `nen` | `https://nen.nipez.cz/profily-zadavatelu-platne` | ⛔ `ConnectionError … Connection aborted` | seznam platných profilů → `/profil/{kód}/XMLdataVZ?od=…&do=…`, záznam = `<zakazka>` |
| `isvz` | `https://isvz.nipez.cz/opendata` | ⛔ `ConnectionError … Connection aborted` | měsíční soubory otevřených dat RVZ dohledané na stránce, záznam = položka souboru |
| `vvz` | `https://api.vvz.nipez.cz/api/submissions/search` | ✅ | formuláře uveřejněné v období (250 na stránku), záznam = formulář (ID = evidenční číslo `F…`) |
| `cedr` | `https://cedropendata.mfcr.cz/c3lod/cedr/` | ⛔ (viz běh) | `Dotace`, `PrijemcePomoci`, `Rozhodnuti` (CSV.gz); historická data, nástupce IS ReD |
| `red` | `https://red.fs.gov.cz/opendata/api/3/action/package_show?id=dotace` | ✅ | `dotace` podepsané v okně + jejich `prijemce-pomoci` a `rozhodnuti` (CSV.gz z katalogu CKAN) |
| `dotaceeu_2127` | stránka seznamu operací na dotaceeu.cz | ✅ | nejnovější měsíční XLSX „Seznam operací 21+“, záznam = řádek (projekt × zakázka) |

SZIF je z v1 vyřazen (D-028), zrcadlo Hlídače státu se ve sběru nepoužívá (D-030).

### Ověřovací běh 26. 9. 2026 (období 26. 8. – 25. 9. 2026)

VYSLEDKY_BEHU
