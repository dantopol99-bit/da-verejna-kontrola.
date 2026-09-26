# Stav platformy veřejné kontroly – předání po cloudové fázi (26. 9. 2026)

Platforma (repozitář `da-verejna-kontrola`) sleduje toky veřejných peněz a napojuje se na kotvu (Firemní databáze)
výhradně přes IČO. Rozhodnutí jsou v `docs/decisions.md` (D-001 až D-055), zdroje v `docs/sources.md`, měření
v `docs/pilot_report.md`, `docs/blok3.md`, `docs/blok4.md`.

## Hotovo

| oblast | stav | kde |
|---|---|---|
| raw (pouze INSERT, hash, evidence běhů, vývojový vzorek) | hotovo | migrace 0001–0008, `pvk.raw`, `pvk.sber` |
| core (bitemporální model, typované částky, toky, události, oprava novou verzí) | hotovo | 0003, 0009–0012, `pvk.core` |
| sběr: VVZ (souhrn + detail eForms s navazováním), IS ReD, seznam operací 21+ | hotovo, ověřeno z cloudu | `make sber` |
| sběr: registr smluv (denní dumpy), NEN, ISVZ, CEDR | napsáno, testováno na vzorových datech | čeká na českou síť |
| normalizace raw → core (IČO + kotva, kurzy ČNB, typ částky, toky po zakázkách/částech) | hotovo | `make normalizace`, D-041, D-044 |
| opakovaný běh bez nových verzí; oprava chyb bez mazání | ověřeno | D-044, D-048 |
| limity ZZVZ 2016–2026 (e-Sbírka) | hotovo | `metodika/limity-zzvz-2026.09.json`, `core.limit` |
| párování smlouva–zakázka | napsáno a testováno; **do výstupů nesmí** (neověřeno) | D-045, D-049 |
| souhrny (jeden zdroj, jeden typ, pokrytí, podíl heuristiky, rozpětí) | hotovo | `pvk.souhrny`, D-046 |
| indikátory: koncentrace, jediná nabídka, zkrácené lhůty (se zákonnými zkráceními), opakovaný příjemce, nový subjekt (stáří v den toku) | spočítáno na vzorku | `make indikatory`, D-050, D-053 |
| prahy | metoda v0.9 schválena, hodnoty ne (brána je blokuje) | D-052, `docs/prahy_navrh.md` |
| publikační brána (build padá při porušení) | hotovo | `pvk.publikace`, `tests/test_publikacni_podminky.py` |
| kontrolní sada z dostupných dat | připravena k potvrzení | `docs/kontrolni_sada.csv` |
| rozhraní pro kotvu (záložka „Veřejné peníze“) | specifikace + funkce | `docs/rozhrani_kotva.md`, `pvk.rozhrani` |

## Čeká na českou síť (servery státu odmítají cloudové adresy – D-033)

* **Registr smluv** (`data.smlouvy.gov.cz`, denní XML dumpy): stahovač `registr_smluv`, ověření hashů příloh (D-030).
  Po stažení: normalizace RS (smlouvy jako toky `smlouva`), ověření vah a prahu párování na ručně potvrzeném vzorku
  (D-049), indikátor dělení pod limit, skupiny kontrolní sady „čeká na zdroj“.
* **NEN** (profily zadavatelů, XML), **ISVZ** (otevřená data), **CEDR** (historické dotace): stahovače dohledávají
  soubory za běhu (D-036); první běh z české sítě ověří předpoklady o struktuře (úprava bude lokální – parser).
* Zrcadlo Hlídač státu smí sloužit jen jako vývojový vzorek, nikdy jako zdroj publikovaných dat (D-040).

## Čeká na kotvu (Firemní databáze)

* `DbKotva` (`pvk.kotva`) – dohodnout pohled/funkci kotvy: údaje subjektu k IČO (název, právní forma, datum vzniku,
  zániku), hromadné ověření IČO, **rizikové pásmo** (indikátor `rizikove_pasmo`), změny v obchodním rejstříku
  (indikátor `zmena_struktury`, přeměny pro nový subjekt). Do té doby ARES (jen paměťová cache, nic se neukládá).
* Záložka „Veřejné peníze“: kotva volá `pvk.rozhrani.verejne_penize()` (schéma `pvk.verejne_penize` 1.0) – způsob
  volání (knihovna, pohled v DB, HTTP) dohodnout s kotvou; do repozitáře kotvy se nezasahuje.

## Čeká na server

* **Trvalá databáze:** PostgreSQL 16 se zálohami (cloudová databáze je dočasná; raw/core/ind jsou pouze INSERT –
  zálohy jsou jediná ochrana proti ztrátě). Úložiště `data/raw` (stažené soubory, ~1 GB/měsíc s ReD) zálohovat také.
* **Denní sběr:** `make sber` (noc), pak `make normalizace`, `make indikatory`, `make gate`; detail VVZ navazuje
  (`LIMIT_MINUT`), ReD se stahuje jen při změně katalogu.
* **Historický import:** registr smluv od 7/2016 (denní dumpy), VVZ od 2016 (souhrny + detail, ~5 400 formulářů
  měsíčně), seznam operací (celý soubor), IS ReD a CEDR (celé soubory). Po importu přepočet prahů na ≥ 12 měsících
  dat a jejich schválení (D-052).

## První spuštění na serveru v ČR – přesný postup

```bash
# 0) systém: Python 3.12, PostgreSQL 16 (nebo Docker), tesseract-ocr + tesseract-ocr-ces, poppler-utils, git
git clone https://github.com/dantopol99-bit/da-verejna-kontrola.git && cd da-verejna-kontrola
cp .env.example .env            # DATABASE_URL na trvalou databázi, PVK_DATA_DIR na zálohovaný disk,
                                # PVK_RS_BACKEND=oficialni, PVK_KOTVA=ares (později db + KOTVA_DATABASE_URL)
make setup                      # .venv + závislosti
make db                         # jen pokud databáze neběží (docker compose / lokální pg_ctl)
make migrate                    # migrace 0001–0013
make test && make lint && make gate   # vše musí projít (testy vytvářejí dočasné databáze pvk_test_*)

# 1) test dostupnosti zdrojů z české sítě (jeden den, rychle)
.venv/bin/python -m pvk.sber sber --zdroje "registr_smluv nen isvz cedr" --od 2026-09-24 --do 2026-09-25
make sber-stav                  # očekávání: registr_smluv / nen / isvz / cedr = uspech (ne preskoceno)

# 2) první měsíc všech zdrojů (detail VVZ po částech, navazuje)
make sber LIMIT_MINUT=60        # opakovat, dokud `python -m pvk.sber uplnost` neukáže zbyva = 0
make normalizace                # raw -> core, docs/blok3.md
make indikatory                 # výsledky do ind, publikační brána
make kontrolni-sada             # docs/kontrolni_sada.csv k ručnímu potvrzení

# 3) historický import po měsících (příklad pro registr smluv a VVZ), pak normalizace a indikátory
for m in $(seq 0 23); do od=$(date -d "2024-10-01 +$m month" +%F); do=$(date -d "$od +1 month" +%F);
  .venv/bin/python -m pvk.sber sber --zdroje "registr_smluv vvz vvz_detail" --od $od --do $do --limit-minut 120; done
make normalizace && make indikatory

# 4) denní běh (cron, 02:15): sběr, normalizace, indikátory, brána
# 15 2 * * * cd /srv/da-verejna-kontrola && make sber LIMIT_MINUT=120 && make normalizace && make indikatory
```

Po prvním běhu z české sítě: zapsat do `docs/sources.md` skutečnou dostupnost a strukturu souborů RS/NEN/ISVZ/CEDR,
případné úpravy parserů jako nové rozhodnutí; ověřit párování na ručně potvrzeném vzorku RS (D-049) a teprve pak
nová verze metodiky párování s `"overeno": true`.

## Měření závěrečné fáze (26. 9. 2026)

* Nový subjekt v2 (stáří v den toku): 12 296 hodnocených toků (VVZ a zakázky v projektech seznamu operací),
  9 745 jedinečných výsledků v `ind` (shodné toky téhož dodavatele a dne se slučují), 37 toků do 365 dní od vzniku
  u 33 dodavatelů (přeměny vyloučeny). Výsledky verze 2026.09 (569) zůstávají v `ind`, ale nevydávají se.
* Zkrácené lhůty v2 (zákonná zkrácení): 9 zadavatelů nad minimálním základem; předběžné oznámení nebo naléhavost
  uvádí 7 z 328 oznámení o zahájení.
* Pohled `ind.indikator_k_publikaci`: jediná nabídka 42, koncentrace 378, nový subjekt 9 745, opakovaný příjemce
  11 394, zkrácené lhůty 9 (žádný výsledek není označen vůči prahu – hodnoty prahů nejsou schválené).
* Kontrolní sada: 35 řádků (30 z dostupných dat, 5 skupin „čeká na zdroj“). Podrobnosti: `docs/blok5_prepocet.json`.

## Otevřené body

1. Detail VVZ za 26. 8. – 25. 9. 2026: staženo 1 701 z 5 364 formulářů (další běh naváže).
2. Seznam operací: spojení řádků téže zakázky nemá identifikátor (jen heuristika) – ponecháno jako řádek = smlouva.
3. Zkrácené lhůty: neověřuje se odstup předběžného oznámení a prodloužení lhůt podle § 57 odst. 1 (jen signál).
4. Opakovaný příjemce: stav k datu i u příjemců bez přiznané částky.
5. Hodnoty prahů: přepočet a schválení na ≥ 12 měsících dat (D-052).
