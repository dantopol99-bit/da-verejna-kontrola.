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
| Detail ve sběru | zdroj `vvz_detail` (`make sber`, hned po `vvz`): `children/search` pro každý formulář období, navazuje na předchozí běhy, `LIMIT_MINUT=N` omezí dobu běhu (D-037); kontakty a údaje o skutečných majitelích se neukládají (D-038) |
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
| **Zpoždění dat** (zjištěno 26. 9. 2026) | export k **21. 2. 2026** (soubory v katalogu upraveny 24. 3. 2026), **poslední datum podpisu** nejpozději k exportu **16. 12. 2025** → data končí ≈ 9 měsíců před dnem ověření; mezi posledním podpisem a exportem 2 měsíce, mezi exportem a zveřejněním další měsíc. Poslední měsíce jsou neúplné (podpisy: 1. pol. 2025 1 300–2 800 měsíčně, 8/2025 746, 9/2025 873, 10/2025 286, 11/2025 77, 12/2025 4). Pravidlo: každý dotační údaj nese stav k datu, chybějící dotace se nevykládá jako žádná dotace (D-039) |
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

Dostupnost ověřena **26. 9. 2026 12:27–12:38 SELČ jedním pokusem bez opakování** přímo v ověřovacím
běhu `make sber` (pokus je v `raw.stazeni` s `beh_id`, výsledek v `raw.beh_prehled`). Blokované zdroje
odmítají spojení z cloudových adres (server spojení ukončí bez odpovědi, u CEDR se nenaváže vůbec); **stahovače poběží beze
změny kódu z české sítě** – stačí `make sber` (nebo `make sber ZDROJE="registr_smluv nen isvz cedr"`).

| Zdroj (`raw.zdroj`) | Test dostupnosti | Výsledek z cloudu | Stahovač (`pvk.sber.sberace`) |
|---|---|---|---|
| `registr_smluv` | `https://data.smlouvy.gov.cz/index.xml` | ⛔ `ConnectionError … Connection reset by peer` | denní dumpy `dump_RRRR_MM_DD.xml` za období, záznam = `<zaznam>` (ID = idVerze) |
| `nen` | `https://nen.nipez.cz/profily-zadavatelu-platne` | ⛔ `ConnectionError … Connection reset by peer` | seznam platných profilů → `/profil/{kód}/XMLdataVZ?od=…&do=…`, záznam = `<zakazka>` |
| `isvz` | `https://isvz.nipez.cz/opendata` | ⛔ `ConnectionError … Connection reset by peer` | měsíční soubory otevřených dat RVZ dohledané na stránce, záznam = položka souboru |
| `vvz` | `https://api.vvz.nipez.cz/api/submissions/search` | ✅ | formuláře uveřejněné v období (250 na stránku), záznam = formulář (ID = evidenční číslo `F…`) |
| `vvz_detail` | `https://api.vvz.nipez.cz/api/submissions/search` | ✅ | detail (eForms) každého formuláře období ze souhrnů `vvz`, záznam = odpověď `children/search` (ID = evidenční číslo `F…`); navazuje (D-037) |
| `cedr` | `https://cedropendata.mfcr.cz/c3lod/cedr/` | ⛔ `ProxyError … 502 Bad Gateway` (spojení se serverem nevzniklo) | `Dotace`, `PrijemcePomoci`, `Rozhodnuti` (CSV.gz); historická data, nástupce IS ReD |
| `red` | `https://red.fs.gov.cz/opendata/api/3/action/package_show?id=dotace` | ✅ | `dotace` podepsané v okně + jejich `prijemce-pomoci` a `rozhodnuti` (CSV.gz z katalogu CKAN) |
| `dotaceeu_2127` | stránka seznamu operací na dotaceeu.cz | ✅ | nejnovější měsíční XLSX „Seznam operací 21+“, záznam = řádek (projekt × zakázka) |

SZIF je z v1 vyřazen (D-028), zrcadlo Hlídače státu se ve sběru nepoužívá (D-030).

### Ověřovací běh 26. 9. 2026 (období 26. 8. – 25. 9. 2026)

| Běh | Zdroj | Stav | Záznamů zpracováno | Nově v raw | Údaj zdroje | Trvání |
|---|---|---|---|---|---|---|
| 1 | `registr_smluv` | preskoceno | 0 | 0 | – | 12 s |
| 2 | `vvz` | uspech | 5 364 | 5 364 | 5 364 | 29 s |
| 3 | `isvz` | preskoceno | 0 | 0 | – | 12 s |
| 4 | `nen` | preskoceno | 0 | 0 | – | 12 s |
| 5 | `red` | uspech | 0 | 0 | – | 536 s |
| 6 | `cedr` | preskoceno | 0 | 0 | – | 0 s |
| 7 | `dotaceeu_2127` | uspech | 48 692 | 48 692 | – | 64 s |
| 8 | `red` | uspech | 68 | 68 | – | 60 s |

Opakovaný běh (stejné období, jen dostupné zdroje) – kontrola, že nevznikají duplicity:

| Běh | Zdroj | Stav | Záznamů zpracováno | Nově v raw | Údaj zdroje | Trvání |
|---|---|---|---|---|---|---|
| 9 | `vvz` | uspech | 5 364 | 0 | 5 364 | 27 s |
| 10 | `dotaceeu_2127` | uspech | 48 692 | 0 | – | 57 s |

**Srovnání s údajem zdroje**

* **VVZ** – zdroj uvádí počet v hlavičce `X-Total-Count`: 5 364; uloženo 5 364 formulářů (shoda).
* **Seznam operací 21+** – zdroj počet neuvádí; soubor „Generováno dne 01.09.2026“ má 48 692 datových
  řádků (projekt × zakázka v projektu), uloženo 48 692 záznamů s 48 692 různými ID (pilot: ≈ 48 700).
  U 1 005 řádků příjemců – fyzických osob se neuložil název ani PSČ.
* **IS ReD** – zdroj počet neuvádí. Export k 21. 2. 2026 (soubory upraveny 24. 3. 2026), poslední datum
  podpisu nejpozději k exportu je 16. 12. 2025 → okno 16. 11. – 16. 12. 2025 (D-022): 23 dotací,
  22 příjemců (u 2 fyzických osob bez jména a roku narození) a 23 rozhodnutí. **Nález kvality dat:**
  ReD se doplňuje se zpožděním – podpisů po měsících: 1. pol. 2025 1 300–2 800 měsíčně, 8/2025 746,
  9/2025 873, 10/2025 286, 11/2025 77, 12/2025 4; poslední měsíc dat je proto neúplný. Běh 5 použil
  chybně okno končící datem exportu (0 záznamů); opraveno, platný je běh 8 (soubory se znovu nestahovaly,
  katalog je od stažení neuvádí jako změněné).
* **Registr smluv, NEN, ISVZ, CEDR** – jeden pokus, spojení odmítnuto; běh ve stavu `preskoceno`
  s chybou v evidenci. Z české sítě: `make sber ZDROJE="registr_smluv nen isvz cedr"`.

Opakovaný běh VVZ a seznamu operací za stejné období nevložil žádný nový záznam (běhy 9 a 10).
Úplný obsah formulářů eForms (částky, dodavatelé) v ověřovacím běhu stažen nebyl (D-034); stahuje ho navazující zdroj `vvz_detail` (D-037) – viz následující oddíl.

### Detail formulářů VVZ – běh 26. 9. 2026 (formuláře ověřovacího běhu 26. 8. – 25. 9. 2026)

Seznam formulářů = souhrny VVZ za období ověřovacího běhu; v tomto prostředí (nová databáze) se souhrny stáhly
znovu – 5 364 formulářů, shodně s `X-Total-Count` i s ověřovacím během. Detail:
`PVK_SBER_OD=2026-08-26 PVK_SBER_DO=2026-09-26 make sber ZDROJE=vvz_detail LIMIT_MINUT=18` (zadání: nejvýš
20 minut). Dotazy po jednom s rozestupem ≥ 0,35 s. Čísla běhů jsou z databáze tohoto prostředí.

| Běh | Zdroj | Stav | Limit | Záznamů zpracováno | Nově v raw | Formulářů v období | Zbývá po běhu | Ukončení | Trvání |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `vvz` | uspech | – | 5 364 | 5 364 | 5 364 | – | – | 27 s |
| 2 | `vvz_detail` | uspech | 0,15 min (zkušební) | 20 | 20 | 5 364 | 5 344 | časový limit běhu | 9 s |
| 3 | `vvz_detail` | uspech | 18 min | 3 071 | 3 071 | 5 364 | 2 273 | časový limit běhu | 18,0 min |

**Stav navazování:** hotovo **3 091** z 5 364 formulářů (57,6 %), zbývá **2 273**. Hotové jsou formuláře F2026-046145 – F2026-049368 (v pořadí evidenčních čísel); příští běh nad stejnou databází
(`make sber ZDROJE=vvz_detail` se stejným obdobím) začne formulářem F2026-049369. Dotazů na detail bylo 3 091 na 3 091 různých URL (žádný formulář se nestahoval dvakrát), všechny s HTTP 200; opakování po čekání (30/60/120 s) nebylo potřeba. Každý detail obsahuje strom eForms (bez stromu: 0); kontakty a osoba zadávající formulář byly vynechány u všech (D-038). Stav kdykoli: `python -m pvk.sber uplnost --od 2026-08-26 --do 2026-09-26`.

**Úplnost stažených detailů** (`python -m pvk.sber uplnost`; počet detailů s vyplněným údajem a podíl v rámci):

| Údaj | všechny stažené detaily: 3 091 | oznámení o zahájení (BT-03 = competition): 1 031 | oznámení o výsledku (BT-03 = result): 1 355 | výsledky s vybraným dodavatelem: 1 208 |
|---|---|---|---|---|
| IČO zadavatele | 3 090 (100,0 %) | 1 031 (100,0 %) | 1 354 (99,9 %) | 1 207 (99,9 %) |
| IČO dodavatele | 1 894 (61,3 %) | 0 (0,0 %) | 1 202 (88,7 %) | 1 202 (99,5 %) |
| předpokládaná hodnota | 2 060 (66,6 %) | 828 (80,3 %) | 1 225 (90,4 %) | 1 104 (91,4 %) |
| vysoutěžená cena | 1 808 (58,5 %) | 0 (0,0 %) | 1 185 (87,5 %) | 1 185 (98,1 %) |
| počet nabídek | 1 355 (43,8 %) | 0 (0,0 %) | 1 355 (100,0 %) | 1 208 (100,0 %) |
| druh řízení | 2 386 (77,2 %) | 1 028 (99,7 %) | 1 355 (100,0 %) | 1 208 (100,0 %) |
| lhůta pro nabídky / žádosti | 1 029 (33,3 %) | 1 027 (99,6 %) | 0 (0,0 %) | 0 (0,0 %) |
| CPV | 3 091 (100,0 %) | 1 031 (100,0 %) | 1 355 (100,0 %) | 1 208 (100,0 %) |
| evidenční číslo zakázky (VVZ) | 3 091 (100,0 %) | 1 031 (100,0 %) | 1 355 (100,0 %) | 1 208 (100,0 %) |
| identifikátor NIPEZ | 2 536 (82,0 %) | 1 029 (99,8 %) | 888 (65,5 %) | 750 (62,1 %) |

* **IČO dodavatele:** 88,7 % oznámení o výsledku, 99,5 % výsledků s vybraným dodavatelem. Rozdíl tvoří 147 oznámení o výsledku bez vybraného dodavatele v kterékoli části (BT-142 ≠ `selec-w`, např. zrušené řízení) – dodavatel tam není, nejde o chybějící údaj; u 6 výsledků s vybraným dodavatelem IČO chybí. Ve všech detailech 61,3 %: oznámení o zahájení dodavatele z povahy věci nemají.
* **Vysoutěžená cena** (hodnota vítězné nabídky BT-720, jinak celková hodnota výsledku BT-161): 87,5 % oznámení o výsledku, 98,1 % výsledků s vybraným dodavatelem (chybí u 23 z 1 208).
* **Evidenční číslo zakázky:** číslo zakázky ve VVZ (`Z…`, v souhrnu formuláře, zdroj `vvz`) má 100,0 % stažených formulářů. Identifikátor zakázky v NIPEZ (`RVZ…`, metadata detailu) má 82,0 %; chybí hlavně u zakázek evidovaných ve VVZ před rokem 2026 (487 z 1 099), u čísel `Z2026-…` jen u 68 z 1 992 (3,4 %). Pro párování se proto používá číslo VVZ.
* **Lhůty** (BT-131 nabídky, BT-1311 žádosti o účast) jsou jen v oznámeních o zahájení: 99,6 %; **počet nabídek** jen ve výsledcích: 100,0 %; **druh řízení** 99,7 % zahájení a 100,0 % výsledků; **CPV** a **IČO zadavatele** prakticky vždy.
* Nejčastější druhy formulářů mezi staženými: 29 (1 299), 16 (898), 38 (645), 17 (111), 39 (47). Stažená část je prvních 3 091 formulářů podle evidenčního čísla, ne náhodný vzorek měsíce; podíly se po dokončení přeměří.

## 9. Blok 3 – vývojové vzorky a normalizace (26. 9. 2026)

Vzorky stažené v nové session (časový rozpočet 8 minut, souběžně): VVZ souhrny za 26. 8. – 25. 9. 2026
(5 364 formulářů), detail eForms s limitem 4 minuty (683 formulářů, zbytek naváže další běh, D-037), seznam
operací 21+ (soubor 2026_09, 48 692 řádků), IS ReD – 23 dotací; stahování příjemců a rozhodnutí ReD přerušil
časový limit (běh `nedokonceno` v `raw.beh`), proto dotace ReD zatím nemají příjemce ani částky (D-039: chybějící
údaj není nula).

* **Zrcadlo Hlídač státu** (vývojový vzorek RS, D-040): 26. 9. 2026 11:34 UTC server ukončil TLS spojení hned po
  ClientHello (tunel proxy prostředí navázán, `recentRelayFailures` prázdné – odmítá cílový server). Záznam
  v `raw.stazeni`, běh `preskoceno`. Neobchází se.
* **Registr smluv – oficiální data**: jeden test dostupnosti 26. 9. 2026 – nedostupné (stejně jako D-033).
* **ČNB – kurzy devizového trhu** (`cnb_kurzy`): roční soubory
  `https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/rok.txt?rok=RRRR`
  dostupné; použití pro přepočet cizích měn (D-041).
* **ARES** (kotva): hromadné ověření IČO `POST /ekonomicke-subjekty/vyhledat` s polem `ico` (100 na dotaz);
  nic se neukládá (D-008).
* **Zákon č. 134/2016 Sb.** pro tabulku limitů: `https://www.zakonyprolidi.cz/cs/2016-134` (aktuální znění
  03.04.2025–31.12.2026); historická znění vyžadují přihlášení – neobchází se (D-042).

## 10. Blok 3/2 – dostupnost (26. 9. 2026, 12:00–12:12 UTC)

* **Registr smluv – oficiální data:** jeden test dostupnosti – nedostupné (běh `preskoceno`).
* **Zrcadlo Hlídač státu:** tentokrát dostupné; test (limit 90 s) stihl 14 smluv jako vývojový vzorek
  (`vyvojovy_vzorek`, D-040), běh ukončený limitem je v `raw.beh` jako `nedokonceno`.
* **IS ReD:** příjemci a rozhodnutí dostaženi (běh `uspech`, 8 minut), soubor dotací se znovu nestahoval (katalog
  CKAN beze změny).
* **e-Sbírka** (`esbirka`): web `e-sbirka.gov.cz` je JavaScriptová aplikace; data znění poskytuje její veřejné
  rozhraní `https://e-sbirka.gov.cz/sbr-cache/dokumenty-sbirky/%2Fsb%2F2016%2F134%2F<datum>` (metadata znění)
  a `…/fragmenty?cisloStranky=N` (text po fragmentech s ELI). `www.e-sbirka.gov.cz` z prostředí nedostupné,
  `www.e-sbirka.cz` přesměruje na `e-sbirka.gov.cz`. Stahuje se přes `Stahovac` (log v `raw.stazeni`).
