# Pilot: měření kvality dat pro Platformu veřejné kontroly

Metodika `pilot-2026.09` ([popis](../metodika/pilot-2026.09.md), [parametry](../metodika/pilot-2026.09.json)) · sledované období 1. 9. 2025 – 31. 8. 2026 · seed 20260925 · vygenerováno 25. 09. 2026 18:07 příkazem `make pilot` (běh 5 min).

Výsledky jsou měření kvality zdrojových dat, ne hodnocení subjektů. Všechny podíly jsou uvedeny s 95% intervalem spolehlivosti (Wilson).

## Shrnutí – čtyři čísla

| # | Měření | Výsledek |
|---|---|---|
| P1 | Registr smluv: IČO obou stran **i** částka v metadatech | **86,5 % (173/200; 95% IS 81,1 %–90,6 %)** |
| P1 | … částka jen v příloze (metadata bez částky, text ano) | 3,0 % (6/200; 95% IS 1,4 %–6,4 %) |
| P1 | … znečitelněné přílohy | 32,5 % (65/200; 95% IS 26,4 %–39,3 %) |
| P2 | Zakázky VVZ spárované se smlouvou v RS **doloženě** | **36,0 % (18/50; 95% IS 24,1 %–49,9 %)** |
| P2 | … **jen heuristicky** (IČO + částka + datum) | **38,0 % (19/50; 95% IS 25,9 %–51,8 %)** |
| P2 | … nespárováno | 26,0 % (13/50; 95% IS 15,9 %–39,6 %) |
| P3 | Opakované/víceleté smlouvy: roční hodnota určitelná **ano** | **31,2 % (10/32; 95% IS 18,0 %–48,6 %)** |
| P3 | … **ne** | 34,4 % (11/32; 95% IS 20,4 %–51,7 %) |
| P3 | … **nejasné** | 34,4 % (11/32; 95% IS 20,4 %–51,7 %) |
| P4 | Příjemci – IS ReD (dotace ze státního rozpočtu a fondů): spárovatelní na IČO přes ARES (příjemci v rozsahu platformy) | **99,5 % (199/200; 95% IS 97,2 %–99,9 %)** |
| P4 | … fyzické osoby bez IČO v celém rámci (mimo rozsah, nespárovatelné z definice) | 92,3 % (12930/14008, úplný výčet) |
| P4 | Příjemci – Seznam operací EU 2021–2027: spárovatelní na IČO přes ARES (příjemci v rozsahu platformy) | **98,5 % (197/200; 95% IS 95,7 %–99,5 %)** |
| P4 | … fyzické osoby bez IČO v celém rámci (mimo rozsah, nespárovatelné z definice) | 0,0 % (1/20264, úplný výčet) |
| P4 | Příjemci – SZIF (zemědělské dotace) | nedostupné: server vrací JavaScriptovou anti-bot výzvu (F5 TSPD) místo dat; ochranu neobcházíme |

**(a) Toky, nebo jen případy?** → **jen případy** (zdůvodnění v kapitole 5).
**(b) Indikátor závislosti na veřejných penězích?** → **ne (v této verzi)** (zdůvodnění v kapitole 5).

## 1. Zdroje a jejich dostupnost

Endpointy jsou popsány v [docs/sources.md](sources.md). Test dostupnosti proběhl v rámci `make pilot` (nejvýš dva pokusy s odstupem 5 s; každý pokus je zapsán v `raw.stazeni`). Měření používají data stažená při prvním běhu pilotu (čas stažení je u každého souboru v `raw.stazeni`).

| Zdroj | Endpoint | Stav | Detail |
|---|---|---|---|
| RS – index dumpů (otevřená data) | `https://data.smlouvy.gov.cz/index.xml` | **nedostupné** | 2. pokus: spojení ukončeno protistranou bez odpovědi (connection reset) |
| RS – web a přílohy smluv | `https://smlouvy.gov.cz/` | **nedostupné** | 2. pokus: spojení ukončeno protistranou bez odpovědi (connection reset) |
| Hlídač státu – zrcadlo RS | `https://www.hlidacstatu.cz/Detail/39673953` | dostupné | HTTP 200 |
| VVZ – API | `https://api.vvz.nipez.cz/api/submissions/search?formGroup=vz&form=vz&page=1&limit=1` | dostupné | HTTP 200 |
| ISVZ – otevřená data VZ | `https://isvz.nipez.cz/opendata` | **nedostupné** | 2. pokus: spojení ukončeno protistranou bez odpovědi (connection reset) |
| NEN | `https://nen.nipez.cz/` | **nedostupné** | 2. pokus: spojení ukončeno protistranou bez odpovědi (connection reset) |
| IS ReD – katalog otevřených dat | `https://red.fs.gov.cz/opendata/api/3/action/package_list` | dostupné | HTTP 200 |
| CEDR III (historické) | `https://cedropendata.mfcr.cz/c3lod/cedr/` | **nedostupné** | 2. pokus: síťová proxy prostředí pilotu cíl nedosáhla (502 Bad Gateway) |
| Seznam operací 21+ | `https://www.dotaceeu.cz/cs/statistiky-a-analyzy/seznam-operaci-(prijemcu)` | dostupné | HTTP 200 |
| SZIF – seznam příjemců | `https://szif.gov.cz/cs/seznam-prijemcu-dotaci` | **anti-bot výzva** | HTTP 200 |

**Registr smluv:** oficiální otevřená data (`data.smlouvy.gov.cz`) ani web `smlouvy.gov.cz` nebyly z prostředí pilotu dosažitelné (spojení ukončeno bez odpovědi serveru; podle monitoringu Hlídače státu, [statniweby/info/128](https://www.hlidacstatu.cz/statniweby/info/128), byl registr smluv v týdnu 18.–25. 9. 2026 nedostupný 58,6 % času i z ČR). P1–P3 proto použily zrcadlo **Hlídač státu** (CC BY 3.0 CZ): metadata záznamů a kopie příloh. Každá kopie přílohy byla přijata jen tehdy, když se její SHA-256 shodoval s hashem přílohy z metadat registru smluv, tj. jde bajtově o tentýž soubor jako originál. Omezení zrcadla: částky jsou zobrazeny zaokrouhlené na celé koruny. Pipeline umí oficiální zdroj (denní dumpy XML) a přepne se na něj sama, jakmile bude dostupný (`PVK_RS_BACKEND=auto`).

**NEN a ISVZ** (otevřená data VZ) nebyly dosažitelné; zakázky se čtou přímo z **Věstníku veřejných zakázek** (veřejné API webu VVZ), kam se oznámení z NEN i ostatních elektronických nástrojů odesílají. **SZIF** vrací místo dat JavaScriptovou anti-bot výzvu; ochranu neobcházíme, registr je v P4 veden jako nedostupný.

## 2. Metoda

* Náhodné výběry jsou deterministické (seed a odvozené seedy pro každé měření); opakované `make pilot` použije již stažená data z `raw.stazeni` a úložiště `data/raw/` (obsahově adresované podle SHA-256).
* Každý vybraný záznam je uložen do `raw.zaznam` se zdrojem, ID ve zdroji, URL, časem stažení a hashem; přílohy jako samostatné záznamy s hashem z metadat i hashem staženého souboru.
* Podrobná pravidla výběrů a verdiktů: [metodika/pilot-2026.09.md](../metodika/pilot-2026.09.md).
* **P1 výběr:** 200 platných záznamů zveřejněných ve sledovaném období. ID verzí v RS se přidělují po čtyřech (zbytek po dělení 4 se v čase mění), proto se losují skupiny čtyř po sobě jdoucích ID v rozsahu 34599641–39350759 a v každé se hledá existující verze. Losováno 216 skupin (222 dotazů): 0 prázdných, 15 neplatných verzí, 1 mimo období, 0 chyb stažení (vyřazeny). Výsledkem je prostý náhodný výběr z platných verzí v období.
* **P2 výběr:** rámec 35786 oznámení o výsledku (eForms 29–35) zveřejněných ve VVZ ve sledovaném období; losováno 54 pozic, vyřazeno: zneplatněný formulář 1, bez uzavřené smlouvy 3.
* **P4 IS ReD:** rámec 14008 příjemců s dotací podepsanou v posledních 12 měsících dostupných dat (17. 12. 2024 – 16. 12. 2025; nejnovější podpis v datech 16. 12. 2025).
* **P4 Seznam operací EU 2021–2027:** rámec 20264 unikátních příjemců (soubor k 1. 9. 2026).

## 3. Výsledky

### P1 – registr smluv

| Ukazatel | Podíl |
|---|---|
| IČO publikujícího subjektu | 100,0 % (200/200; 95% IS 98,1 %–100,0 %) |
| IČO alespoň jedné smluvní strany | 96,0 % (192/200; 95% IS 92,3 %–98,0 %) |
| Částka v metadatech (bez DPH, s DPH nebo v cizí měně) | 89,5 % (179/200; 95% IS 84,5 %–93,0 %) |
| **IČO obou stran i částka** | **86,5 % (173/200; 95% IS 81,1 %–90,6 %)** |
| Metadata bez částky s uvedeným důvodem neuvedení ceny | 3,0 % (6/200; 95% IS 1,4 %–6,4 %) |
| Čitelný text alespoň jedné přílohy | 99,5 % (199/200; 95% IS 97,2 %–99,9 %) |
| **Částka jen v příloze** (z celku) | **3,0 % (6/200; 95% IS 1,4 %–6,4 %)** |
| … ze záznamů bez částky v metadatech | 28,6 % (6/21; 95% IS 13,8 %–50,0 %) |
| **Znečitelněné** (z celku) | **32,5 % (65/200; 95% IS 26,4 %–39,3 %)** |
| … ze záznamů s čitelným textem | 32,7 % (65/199; 95% IS 26,5 %–39,5 %) |

Signály znečitelnění (záznam může mít více signálů): černé obdélníky v PDF 28, textové značky 26, název souboru 23, černé bloky ve skenu 2.

Křížová kontrola metadata × text originálu (počty záznamů):

* částka: shoda 155, metadata bez částky 21, text bez ceny 10, neshoda (výjimka k potvrzení) 10, součet cenových položek z textu 1, cizí měna, v textu nenalezeno 1, násobek periodické částky z textu 1, bez čitelného textu 1
* datum uzavření: shoda 123, nelze ověřit (poslední podpis bez data) 75, neshoda (výjimka k potvrzení) 1, bez čitelného textu 1

Data po záznamech: [docs/pilot_data/p1_vzorek.csv](pilot_data/p1_vzorek.csv).

### P2 – zakázky z VVZ × smlouvy v registru smluv

| Výsledek | Zakázek |
|---|---|
| Doloženě (odkaz BT-151 nebo evidenční číslo v RS) | 36,0 % (18/50; 95% IS 24,1 %–49,9 %) |
| Jen heuristicky (skóre ≥ 0,70) | 38,0 % (19/50; 95% IS 25,9 %–51,8 %) |
| Spárováno celkem | 74,0 % (37/50; 95% IS 60,4 %–84,1 %) |
| Nespárováno | 26,0 % (13/50; 95% IS 15,9 %–39,6 %) |

Rozpad: doloženě odkazem BT-151 na konkrétní smlouvu 11, doloženě jen evidenčním číslem zakázky 7; heuristicky se shodou částky 11, heuristicky jen IČO + datum (skóre na prahu, částku nešlo porovnat nebo nesouhlasí) 8.

Doložené vazby podle metody (zakázka může mít obě): `odkaz_bt151` 11, `evidencni_cislo_vz` 9.
Evidenční číslo zakázky vede u 5 z 9 zakázek na více záznamů RS (rámcové dohody, dynamické nákupní systémy, dílčí smlouvy): dokládá vazbu zakázka → skupina smluv, ne konkrétní smlouvu.
Odkazů BT-151 do RS bylo 19, všechny vedou na existující záznam, 2 na záznam později zneplatněný; u 5 z 19 se datum uzavření v RS a v oznámení liší o více než 30 dní (až 731 dní).
Skóre heuristických vazeb (jen heuristicky spárované zakázky): min 0,700, medián 0,992, max 0,999.
Kontrola heuristiky na doložených případech: u 18 doloženě spárovaných zakázek našla heuristika doložený záznam nad prahem v 10 případech (z toho jako nejlepšího kandidáta v 9). Důvody neshody: evidenční číslo vede na rámcovou/jinou smlouvu téže zakázky 3, v RS chybí částka nebo IČO 1, datum uzavření v RS a ve VVZ se liší více než o okno 3, doložený záznam byl zneplatněn a zveřejněn znovu 1. Heuristika tedy není náhradou doložené vazby: v části případů najde jinou (často správnější, např. dílčí) smlouvu, v části případů doloženou smlouvu nenajde kvůli rozporu dat ve zdrojích.

Skóre všech vazeb je zapsáno v `core.tok_zdroj` (stav, metoda, skóre, verze metodiky); data po zakázkách: [docs/pilot_data/p2_vzorek.csv](pilot_data/p2_vzorek.csv).

### P3 – roční hodnota u opakovaného / víceletého plnění

Z 200 záznamů P1 mělo čitelný text a opakované nebo víceleté plnění **32** smluv (záznamy bez čitelného textu, které nešlo posoudit: 1).

| Lze spolehlivě určit roční hodnotu? | Podíl |
|---|---|
| ano | 31,2 % (10/32; 95% IS 18,0 %–48,6 %) |
| ne | 34,4 % (11/32; 95% IS 20,4 %–51,7 %) |
| nejasné | 34,4 % (11/32; 95% IS 20,4 %–51,7 %) |

* ne: doba neurčitá bez periodické částky – 6
* nejasné: opakované plnění bez údaje o periodě a délce – 5
* ne: text neuvádí cenu plnění – 5
* nejasné: víceletá smlouva s cenou bez výslovné vazby na dobu trvání – 5
* ano: doba plnění nejvýš jeden rok – roční hodnota = cena za celé plnění – 4
* ano: jednoznačná periodická částka (měsíční) – 3
* ano: jednoznačná periodická částka (roční) – 3
* nejasné: více různých periodických částek (roční) – 1

Klasifikace po smlouvách: [docs/pilot_data/p3_klasifikace.csv](pilot_data/p3_klasifikace.csv).

### P4 – příjemci dotací: spárovatelnost na IČO přes ARES

**IS ReD (dotace ze státního rozpočtu a fondů)** – rámec 14008 příjemců: právnické osoby s IČO 958, bez IČO 0; fyzické osoby s IČO 120, bez IČO 12930 (mimo rozsah). Vzorek z 1078 příjemců v rozsahu (n = 200): spárovatelné 99,5 % (199/200; 95% IS 97,2 %–99,9 %); včetně IČO s odlišným názvem 100,0 % (200/200; 95% IS 98,1 %–100,0 %).

* IČO v ARES, název odpovídá: 199
* IČO v ARES, název se liší: 1

**Seznam operací EU 2021–2027** – rámec 20264 příjemců: právnické osoby s IČO 19442, bez IČO 28; fyzické osoby s IČO 793, bez IČO 1 (mimo rozsah). Vzorek z 20263 příjemců v rozsahu (n = 200): spárovatelné 98,5 % (197/200; 95% IS 95,7 %–99,5 %); včetně IČO s odlišným názvem 100,0 % (200/200; 95% IS 98,1 %–100,0 %).

* IČO v ARES, název odpovídá: 197
* IČO v ARES, název se liší: 3

**SZIF (zemědělské dotace):** nedostupné – server vrací JavaScriptovou anti-bot výzvu (F5 TSPD) místo dat; ochranu neobcházíme.

Data po příjemcích (bez identifikace fyzických osob): [docs/pilot_data/p4_vzorek.csv](pilot_data/p4_vzorek.csv).

## 4. Křížová kontrola a výjimky k potvrzení

[docs/pilot_vyjimky.csv](pilot_vyjimky.csv) obsahuje **52** výjimek k potvrzení.

| Měření | Výjimka | `udaj` v CSV | Počet |
|---|---|---|---|
| P1 | částka z metadat v textu nenalezena, text uvádí jiné částky | `castka` | 10 |
| P1 | částka jen v příloze (metadata ji neuvádějí) | `castka_chybi_v_metadatech` | 6 |
| P1 | datum uzavření dřívější než poslední podpis v textu | `datum_uzavreni` | 1 |
| P1 | IČO smluvní strany v textu nenalezeno | `ico_strana` | 15 |
| P1 | IČO publikujícího subjektu v textu nenalezeno | `ico_subjekt` | 9 |
| P3 | roční hodnotu nelze spolehlivě určit | `rocni_hodnota (P3)` | 11 |

Návrhy verdiktů: NELZE OVĚŘIT 23, NESHODA 11, NEJASNÉ 11, ČÁSTKA JEN V PŘÍLOZE 6, NESHODA IČO 1.

Každý řádek má údaj, hodnotu v metadatech, co bylo nalezeno v textu, odkaz na záznam a na originál přílohy a návrh verdiktu. Sloupec `potvrzeno` je prázdný pro vaše potvrzení (ANO / NE / poznámka). Citace z textu smluv se do CSV nepřebírají (mohou obsahovat osobní údaje); u částek je uvedeno klíčové slovo, podle kterého byl kontext označen jako cenový.

## 5. Doporučení

Prahy byly stanoveny **před měřením** v parametrech metodiky (`doporuceni`).

### (a) Systém může tvrdit toky, nebo jen případy?

| Podmínka | Naměřeno | Práh | Splněno |
|---|---|---|---|
| P1 IČO obou stran i částka | 86,5 % | ≥ 90,0 % | ne |
| P2 spárováno doloženě | 36,0 % | ≥ 50,0 % | ne |
| P2 spárováno celkem | 74,0 % | ≥ 80,0 % | ne |

**Doporučení: jen případy.** Platforma má ve v1 zobrazovat jednotlivé případy (zakázka, smlouva, dotace) s odkazem na zdroj a se stavem vazby (doložená / pravděpodobná se skóre), ne agregované toky mezi subjekty. Toky v `core` slouží jako vnitřní struktura; agregovat je lze jen tam, kde jsou vazby doložené a částky stejného typu, a každý souhrn musí nést podíl heuristické deduplikace.

### (b) Indikátor závislosti na veřejných penězích

| Podmínka | Naměřeno | Práh | Splněno |
|---|---|---|---|
| P3 roční hodnota určitelná | 31,2 % | ≥ 80,0 % | ne |
| P4 spárovatelnost – IS ReD | 99,5 % | ≥ 95,0 % | ano |
| P4 spárovatelnost – seznam operací 21+ | 98,5 % | ≥ 95,0 % | ano |
| P4 spárovatelnost – SZIF | neměřeno | ≥ 95,0 % | – |

**Doporučení: ne (v této verzi).** Indikátor závislosti potřebuje roční hodnotu plnění a spolehlivé napojení příjemců na IČO; tam, kde podmínky splněny nejsou, by indikátor sčítal částky s nejasnou periodou nebo neúplný okruh příjemců. Doporučujeme vrátit se k němu po zavedení periody částky z textu smluv (P3) a po ověření výjimek.

Neměřené podmínky: P4 spárovatelnost – SZIF.

## 6. Omezení

* Velikost vzorků (200 / 50 / 200 na registr) dává interval spolehlivosti zhruba ±7 p. b. (n = 200) a ±14 p. b. (n = 50); rozhodnutí blízko prahu je třeba číst s intervalem.
* Detekce částek, dat, znečitelnění a periodicity je pravidlová (regulární výrazy, OCR); verdikty jsou proto výjimkami k potvrzení, ne definitivním zjištěním.
* OCR se provádí jen u stran bez textové vrstvy a nejvýše u 12 stran na přílohu.
* P2 hledá kandidáty ve zrcadle registru smluv (registr nemá vyhledávací API); v produkci bude párování probíhat nad plně načteným registrem v `raw`/`core`.
* IS ReD je publikován se zpožděním; rámec P4 pro ReD je proto posledních 12 měsíců dostupných dat.

## 7. Reprodukce

```
make pilot        # stáhne vzorky (nebo použije stažené), změří P1–P4, vytvoří tento report
make pilot-report # jen přegeneruje report z data/pilot/*.json
```

Mezivýsledky: `data/pilot/*.json`; stažené soubory: `data/raw/<zdroj>/<sha256[:2]>/<sha256>.<přípona>`; původ: tabulky `raw.stazeni` a `raw.zaznam`; výsledky měření: `ind.indikator_vysledek` (kódy `pilot_*`); vazby zakázka–smlouva se skóre: `core.tok_zdroj`.

