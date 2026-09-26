# Rozhodnutí

Formát: kontext → rozhodnutí → důsledky. Číslování je trvalé; překonané rozhodnutí se neškrtá,
ale označí odkazem na nové.

---

## D-001 Migrace: čisté SQL + vlastní malý runner

**Kontext.** Zadání připouští alembic nebo čisté SQL. Schéma stojí hlavně na vlastnostech
PostgreSQL (triggery, EXCLUDE, výčtové typy, PL/pgSQL, vlastní agregát), které alembic stejně
generuje jako ruční SQL.
**Rozhodnutí.** Soubory `db/migrace/NNNN_popis.sql`, runner `pvk.db.migruj()` (tabulka
`public.pvk_migrace`). Aplikovaná migrace se nesmí změnit – runner porovná SHA-256 a při neshodě
skončí chybou.
**Důsledky.** Čitelné, auditovatelné SQL bez ORM. Downgrade se nepíše – oprava = nová migrace.

## D-002 PostgreSQL 16 v Docker Compose na portu 55432

**Kontext.** Kotva (Firemní databáze) může na stejném stroji běžet na výchozím portu 5432.
**Rozhodnutí.** Compose projekt `pvk`, služba `db`, port `55432`, image nastavitelný
(`PVK_PG_IMAGE`, výchozí `postgres:16-alpine`). `scripts/db_up.sh` použije běžící server
z `DATABASE_URL`, jinak Docker Compose, jinak lokální `pg_ctl` (dočasný cluster v `.pgdata/`).
**Důsledky.** `make test` / `make pilot` fungují na stroji s Dockerem i bez něj.

## D-003 raw: tři tabulky, pouze INSERT, hash kanonické podoby

**Rozhodnutí.**
* `raw.zdroj` (evidence zdrojů), `raw.stazeni` (každý pokus o stažení, i neúspěšný, s HTTP
  statusem / chybou, SHA-256, velikostí a cestou v úložišti), `raw.zaznam` (zdrojový záznam).
* Povinné v `raw.zaznam`: `zdroj`, `id_ve_zdroji`, `url` (soubor/URL), `cas_stazeni`, `hash`.
* `hash` = SHA-256 kanonického JSON záznamu (seřazené klíče, UTF-8, bez mezer). Unikátní
  `(zdroj, id_ve_zdroji, hash)`: stejný záznam se podruhé nevloží, změna ve zdroji = nový řádek.
* UPDATE/DELETE/TRUNCATE odmítá trigger `public.pvk_jen_insert()` (SQLSTATE `PV001`) – platí
  i pro vlastníka tabulek. Role s omezenými právy zatím nezavádíme (trigger stačí a je testovaný).
* Soubory (PDF, dumpy, XLSX) leží v obsahově adresovaném úložišti `data/raw/<zdroj>/<sha[:2]>/<sha>`
  mimo git; `raw.stazeni` nese cestu a hash.
**Důsledky.** Původ každého údaje je dohledatelný až k bajtům staženého souboru.

## D-004 core: bitemporální model s registrem klíčů

**Rozhodnutí.**
* Platnost ve světě `valid_from/valid_to` jako `date`, interval `[od, do)`, `infinity` = trvá.
  Čas záznamu `recorded_from/recorded_to` jako `timestamptz`; přiděluje ho databáze (`now()`,
  transakční čas) – klient ho nemůže podstrčit.
* Stabilní klíče entit v `core.entita` (pouze INSERT); každá tabulka entity se na ně odkazuje
  složeným cizím klíčem `(klíč, typ)`, takže klíč toku nemůže ukazovat na subjekt.
* Trigger `core.bitemporalni_straz()`: jediná povolená změna řádku je uzavření verze
  (`recorded_to` z `infinity` na `now()`), DELETE/TRUNCATE nikdy (`PV002`).
* `EXCLUDE USING gist` zakazuje překryv intervalů platnosti mezi aktuálními verzemi jedné entity.
* Změna jen přes `core.zapis_verzi(tabulka, data, valid_from, valid_to)`: uzavře překrývající se
  aktuální verze, jejich zbytky mimo nový interval vloží znovu a vloží novou verzi. Identický
  opakovaný zápis nic nevytvoří (idempotence pro opakované běhy).
* Omezení: dvě změny téže entity v jedné transakci nejsou možné (verzi nelze uzavřít ve stejné
  transakci, ve které vznikla). Zápisy se proto commitují po entitách.
**Důsledky.** Dotaz „jak to bylo platné ke dni D, jak jsme to věděli v čase T“ je jednoduchý
predikát; historie se nikdy neztratí.

## D-005 Částky: povinný typ, DPH, měna, perioda; sčítání napříč typy technicky znemožněno

**Rozhodnutí.**
* Výčtové typy `core.typ_castky` (7 hodnot ze zadání), `core.dph_rezim`
  (`bez_dph`, `vcetne_dph`, `mimo_dph` pro dotace a vratky, `neurceno` když zdroj režim neuvádí –
  „neurčeno“ je explicitní hodnota, ne chybějící údaj), `core.perioda_castky`
  (`celkem`, `rocni`, `mesicni`, `jednotkova`, `neurcena`). Všechny sloupce NOT NULL.
* Perioda chápaná jako časový základ částky. Metadata registru smluv periodu neuvádějí
  (u smluv na dobu neurčitou se podle metodiky RS uvádí hodnota za 5 let, u opakovaného plnění
  za celou dobu), proto se částky z RS zapisují s periodou `neurcena`, dokud ji neurčí text.
* Technická nemožnost sčítání: v SQL složený typ `core.typovana_castka` bez operátoru `+`
  a bez `sum()`; jediný agregát `core.soucet()` vyžaduje shodu typu, měny, režimu DPH i periody,
  jinak `PV003`. `ind.souhrn.castka` je tohoto typu, takže souhrn „přes typy“ nejde ani uložit.
  V Pythonu `pvk.castka.Castka` odmítá `+` s jiným druhem i s čísly (tedy i vestavěné `sum()`).
* Zbytkové riziko: uživatel s přístupem k databázi může ručně sečíst `hodnota` v ad-hoc SQL.
  Systémové výstupy ale vznikají jen přes výše uvedené cesty a publikační bránu.

## D-006 tok_zdroj: skóre 1 je vyhrazeno doloženým vazbám

**Rozhodnutí.** `CHECK ((stav = 'dolozena') = (skore = 1))`. Heuristika je shora omezena
0,999 (parametr metodiky), aby se pravděpodobná vazba nikdy nevydávala za jistou.
Každá vazba nese `metoda` a `metodika_verze_id`.

## D-007 Publikační podmínky ve třech vrstvách

**Rozhodnutí.**
1. Struktura: `ind.indikator_vysledek` má období, počet případů a verzi metodiky NOT NULL;
   `ind.souhrn` má povinný podíl objemu na heuristické deduplikaci a jediný typ částky.
2. Pohledy `ind.indikator_k_publikaci` / `ind.souhrn_k_publikaci` pouštějí ven jen výsledky
   nad minimálním základem dané verze metodiky a bez hodnotících slov.
3. Publikační brána `pvk.publikace` (spouští `make gate`, `make pilot` a testy): kontroluje
   výstupy v `vystupy/` (JSON: indikátor, souhrn, částka, profil, text; texty .md/.txt/.html/.csv)
   a report pilotu. Test `test_vystupy_repozitare_splnuji_publikacni_podminky` shodí build.
* Hodnotící výrazy se hledají ve všech tvarech (podezřelý/podezření, rizikov* dodavatel*,
  propojen* s/se, napojen* na). Podstatná jména „napojení na“ / „propojení s“ (technické
  napojení na kanalizaci) hodnotící nejsou; text bez diakritiky se posuzuje přísně.
  Stejné vzory jsou v SQL (`ind.obsahuje_hodnotici_slova`), shodu hlídá test.
* Nad rámec zadání brána odmítá profil subjektu, který není prokazatelně právnická osoba
  (pravidlo „fyzické osoby se nikdy nezobrazují jako samostatné profily“).

## D-008 Kotva: rozhraní `Kotva`, v pilotu ARES, nic se neukládá

**Rozhodnutí.** `pvk.kotva.subjekt_podle_ico()` nad rozhraním `Kotva`. Pilot: `AresKotva`
(REST API ARES, `GET /ekonomicke-subjekty/{ico}`, hledání podle názvu `POST .../vyhledat`),
jen paměťová cache po dobu běhu. `DbKotva` je připravené místo pro dotaz do databáze kotvy;
schéma kotvy tento repozitář nezná a do kotvy nezasahuje – implementace vznikne po dohodě
rozhraní (pohled/funkce kotvy). Do výstupů pilotu se z ARES nepřebírají názvy ani adresy,
jen výsledek párování (kategorie, skóre podobnosti).
**Důsledky.** `core.subjekt` obsahuje jen IČO; žádná lokální kopie registru subjektů.

## D-009 Minimalizace osobních údajů v raw

**Kontext.** IS ReD zveřejňuje i příjemce – fyzické osoby bez IČO (jméno, příjmení, rok narození).
Pro platformu jsou mimo rozsah (nemají IČO, nelze je napojit na kotvu) a zobrazovat je nelze.
**Rozhodnutí.** U záznamů fyzických osob bez IČO se identifikační pole do `raw.zaznam.obsah`
neukládají; jejich názvy jsou ve sloupci `redigovano`. Hash se počítá z úplného původního záznamu,
takže je možné ověřit, že záznam pochází z daného zdrojového souboru.
**Důsledky.** raw zůstává věrný zdroji ve všem kromě vyjmenovaných osobních údajů.

## D-010 Umístění entit mezi schématy

**Rozhodnutí.** `metodika_verze` a `limit` jsou v `core` (bitemporální, odkazují se na ně
vazby `tok_zdroj` i výsledky), `indikator_vysledek` a `souhrn` v `ind` jako pouze INSERT
(přepočet = nové řádky s novou verzí metodiky, nikoli nová verze starého řádku).

## D-011 TLS: doplnění chybějícího mezilehlého certifikátu

**Kontext.** Server otevřených dat IS ReD (`red.fs.gov.cz`) neposílá mezilehlý certifikát
Thawte TLS RSA CA G1; bez něj ověření TLS selže.
**Rozhodnutí.** Certifikát (z oficiálního úložiště DigiCert, SHA-256 otisk v souboru) je
v `certs/extra-intermediates.pem` a přidává se ke kořenům prostředí. Ověřování TLS se nikdy
nevypíná.

## D-012 Registr smluv v pilotu: oficiální data, při nedostupnosti zrcadlo Hlídač státu

**Kontext.** `data.smlouvy.gov.cz` ani `smlouvy.gov.cz` nebyly z prostředí pilotu dosažitelné
(TLS spojení ukončeno bez odpovědi; monitoring Hlídače státu ukazuje v týdnu pilotu nedostupnost
registru 58 % času i z ČR). Bez registru smluv nelze změřit P1–P3.
**Rozhodnutí.** `PVK_RS_BACKEND=auto`: nejdřív rychlý test oficiálních dat (výsledek v `raw.stazeni`),
při neúspěchu zrcadlo Hlídač státu (CC BY 3.0 CZ; `robots.txt` stránky detailu a vyhledávání
nezakazuje). Z Hlídače bereme jen údaje registru smluv (metadata, kopie příloh); jeho odvozené údaje
(K-Index, politické vazby, sponzoring) ignorujeme. Kopie přílohy se přijme jen při shodě SHA-256
s hashem z metadat RS. Dotazy šetrně: ≥ 1 s mezi dotazy, cache v `raw.stazeni`.
**Důsledky.** Částky ze zrcadla jsou zaokrouhlené na celé Kč (tolerance 1 Kč při kontrolách).
Oficiální cesta (denní dumpy) je implementovaná a otestovaná na syntetickém dumpu podle XSD;
po obnovení dostupnosti ji pipeline použije sama. Registr nemá vyhledávací API – vyhledávání pro P2
jde vždy přes zrcadlo; v produkci nahradí plný import dumpů do `raw`/`core`.

## D-013 Veřejné zakázky z API webu VVZ

**Kontext.** Otevřená data ISVZ (`isvz.nipez.cz/opendata`) ani NEN nebyly dosažitelné. Web VVZ
(`vvz.nipez.cz`) je aplikace nad veřejným JSON API `api.vvz.nipez.cz` (bez přihlášení).
**Rozhodnutí.** Pilot čte oznámení o výsledku (eForms 29–35) z `/api/submissions/search` a úplný
formulář z `/api/submissions/children/search`. API není formálně dokumentováno jako otevřená data –
používáme ho šetrně a v `docs/sources.md` to uvádíme. Oznámení z NEN se do VVZ odesílají, takže
VVZ pokrývá i zakázky z NEN.
**Důsledky.** Klíčový nález: pole eForms **BT-151 (URL smlouvy)** často obsahuje přímý odkaz do
registru smluv – doložená vazba zakázka → smlouva bez heuristiky.

## D-014 SZIF: anti-bot výzva se neobchází

**Rozhodnutí.** Otevřená data SZIF (`szif.gov.cz/cs/CmOpendata`) vracejí JavaScriptovou výzvu F5 TSPD
místo souboru. Neobcházíme ji (pravidlo 1 – jen legálně dostupná data, neobcházet ochrany).
Registr je v P4 veden jako nedostupný; řešení: ověřit z české sítě, případně požádat SZIF o přímý
přístup k souborům otevřených dat.

## D-015 Stabilní klíče entit z přirozených klíčů

**Rozhodnutí.** Pipeline zakládá entity `core` s klíčem UUIDv5 z přirozeného klíče
(např. `tok:vvz:F2025-052084:CON-0001`), `pvk.core.zapis_entitu()`. Opakovaný běh tak nezaloží
duplicitní entitu a díky idempotenci `core.zapis_verzi()` ani novou verzi.

## D-016 P4: fyzické osoby bez IČO se nelosují, jejich podíl se počítá na celém rámci

**Kontext.** První běh P4 ukázal, že v IS ReD tvoří fyzické osoby bez IČO (právní forma 998)
naprostou většinu příjemců posledních 12 měsíců dat (183 z 200 vylosovaných). Takové příjemce nelze
z definice napojit na IČO a jsou mimo rozsah platformy.
**Rozhodnutí.** (Změna návrhu po prvním běhu, uvedeno transparentně.) Složení rámce (PO/FO × s IČO/
bez IČO) se počítá přesně na celém rámci; vzorek 200 pro párování se losuje z příjemců v rozsahu
(právnické osoby a podnikající fyzické osoby s IČO). Report uvádí obě čísla. Záznamy z prvního běhu
zůstávají v `raw` (vrstva je pouze pro INSERT) a jsou identifikovatelné časem vložení.

## D-017 P1 ze zrcadla: výběr po skupinách čtyř ID

**Kontext.** ID verzí v RS se přidělují s krokem 4; zbytek po dělení 4 se v čase mění (v období
pilotu 1, 0, 3). Losování jednotlivých ID by stálo ~4× více dotazů, omezení na jeden zbytek by
vynechalo části období.
**Rozhodnutí.** Losuje se skupina čtyř po sobě jdoucích ID (rovnoměrně v rozsahu období s rezervou),
v ní se zkouší ID v pořadí podle zbytku nejbližšího známého ID; skupina bez verze, neplatná verze
nebo verze mimo období se odmítne. Ve skupině je nejvýš jedna verze, výsledkem je prostý náhodný
výběr z platných verzí v období.

## D-018 P2: doložená vs. pravděpodobná vazba zakázka → smlouva

**Rozhodnutí.** Doložená (skóre 1): BT-151 odkazuje na existující záznam RS, nebo je evidenční
číslo zakázky (Z…) nalezeno v záznamu RS se shodným IČO zadavatele. Pravděpodobná: kandidát ze
zrcadla RS se shodným IČO zadavatele i dodavatele a datem podpisu v okně ±30 dní od BT-145;
skóre = 0,4 + 0,3 × shoda data + 0,3 × shoda částky (tolerance 10 %, přepočet DPH 21/12 %),
práh 0,70, maximum 0,999. Všechny vazby se zapisují do `core.tok_zdroj`; heuristika se kontroluje
na doloženě spárovaných zakázkách.

## D-019 Výjimky k potvrzení bez citací textu smluv

**Rozhodnutí.** `docs/pilot_vyjimky.csv` obsahuje hodnoty (částky, data, IČO), odkazy na záznam
a originál a návrh verdiktu, ale ne úryvky textu smluv: úryvky mohou obsahovat osobní údaje
a technické formulace, které by publikační brána (oprávněně) zachytila. U částek se uvádí klíčové
slovo cenového kontextu. Úryvky jako důkaz zůstávají lokálně v `data/pilot/*.json`.

## D-020 Prahy doporučení se stanovují před měřením

**Rozhodnutí.** Prahy pro doporučení (a) toky vs. případy a (b) indikátor závislosti jsou
v `metodika/pilot-2026.09.json` (`doporuceni`) a report je aplikuje mechanicky; komentář je oddělený.

## D-021 Log stažení nese vybrané HTTP hlavičky

**Rozhodnutí.** Migrace 0005 přidává `raw.stazeni.hlavicky` (Last-Modified, ETag, X-Total-Count,
Content-Range…). Doklad stavu zdroje v okamžiku stažení; `X-Total-Count` určuje rámec výběru ve VVZ.

## D-022 IS ReD: okno podle data exportu

**Kontext.** V `dotace.csv` se vyskytují data podpisu po datu exportu (např. 2030-06-17) – chyba dat.
**Rozhodnutí.** Konec okna „posledních 12 měsíců dat“ = nejnovější datum podpisu nejpozději k datu
exportu; podpisy po exportu se počítají a uvádějí jako nález kvality dat.

## D-023 Výsledky měření pilotu v `ind.indikator_vysledek`

**Rozhodnutí.** Každé číslo pilotu se zapisuje jako výsledek s kódem `pilot_*`, obdobím, počtem
případů (n), verzí metodiky a neutrálním textem; prochází tak stejnými podmínkami publikace jako
budoucí indikátory (minimální základ 30 případů).

## D-024 Kalibrace pravidel detekce během pilotu (prahy doporučení beze změny)

**Kontext.** Pravidlová detekce (částky, data podpisu, znečitelnění, periodicita) se poprvé setkala
se skutečnými smlouvami. Ruční kontrola vzorku nálezů ukázala systematické chyby: „ze dne“ u odkazů
na usnesení se počítalo jako datum podpisu; částky v tabulkách bez označení měny se nenašly; tmavé
řádky tabulek, záhlaví se světlým textem a sloupcové grafy se hlásily jako začernění; smluvní doložky
o uveřejnění („údaje, které by jinak podléhaly znečitelnění“) se počítaly jako textová značka
znečitelnění; záruční doba a udržitelnost projektu se počítaly jako doba plnění; jednotkové ceny
(Kč/m² ročně) jako roční hodnota; jako „částka jen v příloze“ se počítaly hodinové sazby, spoluúčast
pojištění nebo prahy („v hodnotě vyšší než“) a čísla navazující na jednotku („m3 EUR“) jako částky.
**Rozhodnutí.** Pravidla byla zpřesněna (popis v `metodika/pilot-2026.09.md`, každá úprava má test
v `tests/test_pilot.py`), mezivýsledky přepočteny z uložených dat. Prahy doporučení
(`doporuceni`) ani definice měřených podílů se neměnily. Verze detekce je v cache textu
(`VERZE_DETEKCE`), takže změna pravidel vynutí přepočet.
**Důsledky.** Výjimky v `docs/pilot_vyjimky.csv` odrážejí zpřesněná pravidla; zbývající nejistota
je právě to, co má potvrdit člověk.

## D-025 Oprava pohledu k publikaci novou migrací

Pohled `ind.indikator_k_publikaci` vyřazoval výsledky, když metodika uváděla `"min_zaklad": null`.
Oprava je v migraci 0006 (aplikovaná migrace 0004 se nemění, D-001); regresní test
`test_db_min_zaklad_null_znamena_bez_minima_objemu`.

## D-026 (D1 po pilotu) Toky jen v rámci jednoho zdroje a jednoho typu částky

**Kontext.** Pilot (docs/pilot_report.md) nesplnil prahy pro tvrzení toků napříč zdroji: P1 86,5 %
(práh 90 %), P2 doloženě 36 % (práh 50 %), P2 celkem 74 % (práh 80 %).
**Rozhodnutí.** Souhrny v rámci jednoho zdroje a jednoho typu částky se smějí tvrdit jako toky, vždy
s uvedeným pokrytím (podíl záznamů s IČO obou stran a částkou). Propojení zakázka → smlouva se
zobrazuje jen jako případy se stavem shody (doložená / pravděpodobná se skóre), nikdy jako tok.
**Důvod.** Sčítání napříč typy částky je technicky zakázané (D-005); deduplikace mezi zdroji se souhrnů
v rámci jednoho zdroje netýká, takže je neohrožuje.
**Důsledky.** Souhrn nese zdroj, typ částky a pokrytí; publikační brána dál odmítá souhrn přes více typů.

## D-027 (D2 po pilotu) Indikátor závislosti na veřejných penězích se ve v1 nevydává

**Kontext.** Roční hodnotu opakovaného plnění lze spolehlivě určit jen u 31 % smluv (P3, práh 80 %).
**Rozhodnutí.** Indikátor se ve v1 nevydává. Tržby (z kotvy) a smluvní objem se zobrazují vedle sebe,
bez podílu.
**Důsledky.** Žádný výstup nesmí počítat podíl smluvního objemu na tržbách.

## D-028 (D3 po pilotu) SZIF je z v1 vyřazen

**Kontext.** Seznam příjemců SZIF vrací anti-bot výzvu (D-014); ochrana se neobchází.
**Rozhodnutí.** Zemědělské dotace SZIF nejsou součástí v1. Podmínka P4 pro SZIF se nevyhodnocuje.
**Důsledky.** Pokrytí dotací ve v1 = IS ReD a seznam operací EU 2021–2027; výstupy to uvádějí.

## D-029 (D4 po pilotu) Prahy pilotu 90 / 50 / 80 % jsou metodické

**Rozhodnutí.** Prahy pro tvrzení toků napříč zdroji (P1 ≥ 90 %, P2 doloženě ≥ 50 %, P2 celkem ≥ 80 %)
jsou potvrzeny jako metodické: platí pro každé další měření a mění se jen novou verzí metodiky
stanovenou před měřením.

## D-030 (D5 po pilotu) Zrcadlo Hlídače státu jen pro pilot

**Kontext.** Oficiální data registru smluv nebyla z prostředí pilotu dostupná (D-012).
**Rozhodnutí.** Zrcadlo Hlídač státu smí použít jen pilot. V provozu se používají výhradně oficiální
zdroje: výchozí `PVK_RS_BACKEND=oficialni`, `HlidacRS` jde vytvořit jen s `pilot=True` (jinak
`PermissionError`), pilot má vlastní volbu `PVK_PILOT_RS_BACKEND` (výchozí `auto`). Oficiální stahovač
(`OficialniRS`) ověřuje SHA-256 každé přílohy proti hashi z oficiálních metadat (dump) a přílohu
s jiným hashem odmítne (`NeshodaHashe`). Protože oficiální zdroj nebyl dostupný, je stahovač otestován
na vzorových datech (`tests/test_oficialni_rs.py`).

## D-031 Výjimky pilotu: kategorie přijaté automaticky

**Rozhodnutí.** Výjimky „nelze ověřit“ (text přílohy IČO neuvádí) a „nejasná roční hodnota“ (P3) se
přijímají automaticky jako kategorie a jsou v `docs/pilot_vyjimky_kategorie.csv`. K ručnímu potvrzení
v `docs/pilot_vyjimky.csv` zůstávají jen neshody částky a data, částka jen v příloze a jiné IČO v textu.

## D-032 Přeměření P1 a P2 po pilotu

**Kontext.** Zadání: P1 se vzorkem 500 smluv a P2 se 100 zakázkami, při riziku překročení časového
rozpočtu session (30 min) nejméně 300 a 60.
**Rozhodnutí.** Kvůli časovému rozpočtu 300 smluv a 60 zakázek. P1 se přeměřuje jen z metadat
(kontrola proti textu originálů proběhla v pilotu na 200 smlouvách a neopakuje se). Výběr používá
stejný seed, takže vzorek pilotu je prefixem nového vzorku. Oficiální zdroje registru smluv nebyly
dostupné, P1 i kandidáti P2 proto pocházejí ze zrcadla; report to u každého čísla uvádí.

## D-033 Sběr do raw: evidence běhů a nedostupné zdroje

**Kontext.** Blok 2 – pravidelný sběr ze zdrojů. Registr smluv, NEN, ISVZ a CEDR odmítají spojení
z cloudových adres (servery státu, ne síťové omezení prostředí).
**Rozhodnutí.** `make sber` (`python -m pvk.sber`) spustí stahovače všech zdrojů za období (výchozí
poslední měsíc `[dnes − 1 měsíc, dnes)`, `PVK_SBER_OD/DO`, výběr `ZDROJE="vvz red"`). Každý běh má
evidenci v migraci 0007: `raw.beh` (začátek, zdroj, období, parametry) a `raw.beh_konec` (konec, stav
`uspech | chyba | preskoceno`, počet zpracovaných a nově vložených záznamů, počet uváděný zdrojem, chyby);
obě pouze INSERT, konec běhu je samostatný řádek (běh bez konce = `nedokonceno`). `raw.stazeni` a
`raw.zaznam` nesou `beh_id`. Před sběrem proběhne **jeden** test dostupnosti bez opakování; nedostupný
zdroj se přeskočí se stavem `preskoceno` a chybou spojení v evidenci – nic se neobchází. Návratový kód
je 1 jen při chybě dostupného zdroje. Přehled: `make sber-stav` (pohled `raw.beh_prehled`).
**Důsledky.** Opakovaný běh nevytvoří duplicity (`raw.zaznam` je unikátní podle zdroje, ID a hashe);
změna záznamu ve zdroji = nový řádek. Blokované zdroje poběží stejným příkazem z české sítě.

## D-034 Ověřovací běh: období a srovnání se zdrojem

**Rozhodnutí.** VVZ: všechny formuláře uveřejněné v období (souhrn formuláře z vyhledávání API),
počet se porovnává s hlavičkou `X-Total-Count`. IS ReD: dotace podepsané v období + jejich příjemci
a rozhodnutí; končí-li data před začátkem období (ReD se publikuje se zpožděním), použije se stejně
dlouhé okno končící posledním datem podpisu nejpozději k datu exportu (D-022) a skutečné okno se zapíše
do poznámky běhu. Soubory ReD (≈ 600 MB) se znovu stahují jen tehdy, když je katalog CKAN (`last_modified`)
uvádí jako změněné po posledním stažení. Seznam operací 21+: nejnovější měsíční soubor (celý, řádek =
projekt × zakázka v projektu, ID = registrační číslo # číslo řádku). Zdroj počet neuvádí → srovnává se
s počtem řádků souboru.
**Důsledky.** Úplný obsah formulářů eForms (`children/search`, částky a dodavatelé) stahuje zatím jen
adaptér pilotu; do sběru se doplní v dalším bloku (≈ 5 400 dotazů měsíčně nešlo v časovém rozpočtu).

## D-035 Osobní údaje ve sběru

**Rozhodnutí.** Rozšíření D-009 pro vnořené záznamy: `raw.zapis_zaznam(ulozeny_obsah=…)`, v `redigovano`
jsou cesty vynechaných polí, hash je vždy z původního záznamu. Vynechává se: u VVZ osoba zadávající
formulář (`owner`, `createdBy`, `updatedBy`, `uzivatelVvzLogin`); kontaktní údaje osob ve všech
zdrojích (e-mail, telefon, kontaktní osoba); u stran bez IČO (smluvní strana RS, dodavatel NEN/ISVZ,
dodavatel a poddodavatel v seznamu operací) název a adresa; u příjemců ReD/CEDR jméno, příjmení
a rok narození; u příjemců – fyzických osob v seznamu operací název a PSČ.

## D-036 Stahovače blokovaných zdrojů: dohledání souborů místo pevných cest

**Kontext.** Přesné cesty k souborům ISVZ a CEDR a stránkování seznamu profilů NEN nešlo z cloudu ověřit.
**Rozhodnutí.** Stahovače hledají soubory za běhu: ISVZ – odkazy na stránce `isvz.nipez.cz/opendata`,
jejichž název obsahuje rok a měsíc období (JSON/XML/CSV, i v ZIP/GZIP); NEN – profily ze seznamu
platných profilů (včetně stránek; `PVK_SBER_NEN_PROFILY` omezí výběr) a pro každý profil
`/profil/{kód}/XMLdataVZ?od=DDMMRRRR&do=DDMMRRRR`; CEDR – odkazy ze stránky otevřených dat, jinak
`c3lod/{Dotace|PrijemcePomoci|Rozhodnuti}.csv.gz`; registr smluv – denní dumpy. Nenalezený soubor je
chyba v evidenci běhu, ne pád. Stahovače jsou otestované na vzorových datech (`tests/test_sber.py`).
**Důsledky.** První běh z české sítě ověří předpoklady o struktuře; případná úprava bude malá a lokální
(parser záznamů, vzor názvu souboru).

## D-037 Detail formulářů VVZ: navazující sběr

**Kontext.** D-034 odložil úplný obsah formulářů eForms (≈ 5 400 dotazů měsíčně). Z detailu jsou IČO
zadavatele a dodavatele, předpokládaná hodnota, vysoutěžená cena, počet nabídek, druh řízení, lhůty a CPV.
**Rozhodnutí.** Samostatný zdroj `vvz_detail` (stejné API, `/api/submissions/children/search?submission={id}`);
záznam raw = odpověď API pro jeden formulář, ID = evidenční číslo formuláře (shodné se souhrnem ve zdroji
`vvz`). Seznam formulářů se bere ze souhrnů v raw za období (proto v `make sber` běží hned po `vvz`),
v pořadí evidenčních čísel. **Navazování:** formulář, jehož detail už je v raw, se přeskočí; každý
formulář se potvrdí (commit) hned po uložení, takže přerušený běh (časový limit, pád, Ctrl+C) pokračuje
dalším nestaženým formulářem; odpověď stažená bez uloženého záznamu se vezme z `raw.stazeni`, znovu se
nestahuje (stažení se evidují pod zdrojem `vvz` – stejné API, sdílená cache s adaptérem pilotu).
Jeden detail na formulář – oprava je ve VVZ nový formulář s novým evidenčním číslem.
**Tempo:** dotazy po jednom, ≥ 0,35 s mezi dotazy na `api.vvz.nipez.cz` (D-013); při chybě spojení, 429
a 5xx opakuje `pvk.http` (včetně Retry-After) a nad ním další pokusy po 30, 60 a 120 s; tři formuláře
za sebou nestažené → běh končí, zbytek příště. `LIMIT_MINUT` (`--limit-minut`) omezí dobu běhu.
Stav a úplnost: `python -m pvk.sber uplnost [--od --do]`.
**Důsledky.** Měsíc formulářů lze stahovat po částech; evidence běhu uvádí `pocet_ve_zdroji` = formulářů
v období podle souhrnů a v poznámce `hotovo_pred_behem`, `stazeno_v_behu`, `zbyva`, případně `ukonceno`.
Údaje z detailu čte `pvk.zdroje.vvz.udaje_detailu()` (částky jako dvojice hodnota–měna, bez sčítání).

## D-038 Osobní údaje v detailu formulářů VVZ

**Rozhodnutí.** Rozšíření D-035 pro strom eForms: vynechávají se kontaktní údaje všech organizací
a kontaktních míst (BT-502 kontaktní místo/osoba, BT-503 telefon, BT-506 e-mail, BT-739 fax), osoba
zadávající formulář (`owner`, `createdBy`, `updatedBy`) a všechna pole o skutečných majitelích (UBO) –
údaje o skutečných majitelích se nepoužívají (pravidlo 2); u organizace bez IČO (BT-501) název a adresa.
Hash je z původní odpovědi, cesty vynechaných polí jsou v `redigovano`.

## D-039 Dotační údaj nese stav k datu; chybějící dotace není žádná dotace

**Kontext.** IS ReD se publikuje se zpožděním: export k 21. 2. 2026 (soubory upraveny 24. 3. 2026),
poslední datum podpisu k datu exportu 16. 12. 2025, poslední měsíce před exportem jsou neúplné
(12/2025: 4 podpisy proti 1 300–2 800 měsíčně v 1. pololetí 2025). Viz `docs/sources.md`, oddíl 4.
**Rozhodnutí.** Každý dotační údaj nese **stav k datu**: datum exportu zdroje (a čas stažení z `raw.stazeni`)
prochází z raw přes core a ind až do výstupu a výstup ho uvádí u každého čísla („IS ReD, stav k 21. 2. 2026“).
**Chybějící dotace se nikdy nevykládá jako žádná dotace:** subjekt nebo období bez záznamu v registru
dotací = „v datech zdroje ke dni … nenalezeno“, nikdy „dotaci nečerpal“ ani nulová částka; nulu nelze
odvodit z chybějícího záznamu. Období po posledním datu podpisu ve zdroji a měsíce zjevně neúplné se
označí jako neúplné a do srovnání se nezahrnují.
**Důsledky.** Metodiky indikátorů s dotacemi musí mít datum stavu dat jako povinný parametr výsledku
a pohled k publikaci dotační údaj bez něj nesmí vydat (vynutí se testem publikačních podmínek s prvním
dotačním výstupem). Zpoždění ReD se přeměřuje při každém sběru (poznámka běhu `okno_podle_dat`: datum
exportu a poslední podpis).

## D-040 Zrcadlo Hlídače státu jen jako vývojový vzorek, nikdy zdroj publikovaných dat

**Kontext.** Blok 3 potřebuje reálné smlouvy registru smluv pro vývoj normalizace; oficiální data RS jsou
z cloudu blokovaná (D-033). Zadání: 300 smluv ze zrcadla jako vývojový vzorek.
**Rozhodnutí.** Rozšíření D-030: zrcadlo Hlídač státu smí kromě pilotu sloužit jen jako **vývojový vzorek**
(`HlidacRS(..., vyvojovy_vzorek=True)`, stahovač `hlidac_statu_rs` jen výslovně
`python -m pvk.sber sber --zdroje hlidac_statu_rs`, nikdy ve výchozím `make sber`). Záznamy nesou v raw příznak
`raw.zaznam.vyvojovy_vzorek` (migrace 0008); záznam zrcadla bez příznaku databáze odmítne (CHECK, pro nové
řádky) a `pvk.raw.zapis_zaznam` ho u zdroje zrcadla nastaví vždy. Publikační brána odmítne výstup
s `vyvojovy_vzorek` nebo ze zdroje zrcadla (`VYVOJOVY_VZOREK`). Publikovaná data stojí jen na oficiálních zdrojích.
**Stav 26. 9. 2026.** Zrcadlo ukončilo TLS spojení hned po ClientHello (stejně jako oficiální RS, D-012/D-033);
test dostupnosti je v `raw.stazeni` a běh `preskoceno` v `raw.beh`. Ochrana se neobchází, vzorek RS v raw
proto zatím není; stahovač poběží stejným příkazem, jakmile bude zdroj dostupný.

## D-041 Normalizace raw -> core: toky, částky, IČO, kurzy

**Rozhodnutí.**
* **Tok v rámci jednoho zdroje** (D-026) s přirozeným klíčem: VVZ `vvz:<ev. číslo zakázky>` (všechny formuláře
  zakázky – zahájení, výsledek, opravy, změny – se na tok navazují), seznam operací `dotaceeu_2127:<registrační
  číslo>` (dotace) a `dotaceeu_2127:<reg#řádek>` (veřejná zakázka v projektu: příjemce dotace -> dodavatel),
  IS ReD `red:<iriDotace>`. První záznam tok založí, další se navazují; každá vazba je v `core.tok_zdroj` jako
  doložená (skóre 1, metoda `identifikator_ve_zdroji`) – tok určuje identifikátor ve zdroji, ne heuristika.
* **Události, nic se nepřepisuje:** zveřejnění formuláře, oznámení o změně smlouvy (eForms 38–40) = `dodatek`,
  příznak zrušení zakázky = `zruseni` (nový typ, migrace 0009), zneplatněný formulář = `zneplatneni`, uzavření
  smlouvy (BT-145), podepsání právního aktu = `rozhodnuti_o_dotaci`.
* **Bitemporalita:** `valid_from` = datum události ve světě (uveřejnění, uzavření, podpis právního aktu; čerpání
  k datu souboru), `recorded_from` přiděluje databáze.
* **Typ částky podle metodiky** `metodika/normalizace-2026.09.json` (pole zdroje -> typ, režim DPH, perioda);
  částku bez pravidla nebo bez měny adaptér nezapíše a zapíše výjimku. Hodnoty eForms (BT-27, BT-720, BT-161)
  jsou podle definice eForms bez DPH.
* **IČO:** doplnění nul, kontrola modulo 11, neplatné -> výjimka. IČO, které platforma nezná, se ověří hromadně
  v kotvě (`Kotva.subjekty_podle_ico`, v pilotu ARES `vyhledat` po 100 IČO); z kotvy se nic neukládá, do
  `core.subjekt` jde jen IČO ověřené kotvou. Nenalezené IČO -> výjimka, strana toku zůstane neurčená s důvodem.
* **Cizí měna:** kurz ČNB (roční soubor, kurz vyhlášený nejpozději v den uzavření, nejvýš 10 dní starý) do
  `hodnota_czk`, `kurz_cnb`, `kurz_datum`; původní `hodnota` a `mena` zůstávají. Bez kurzu `prepocet =
  'kurz_nedostupny'` a výjimka. Soubory kurzů jdou přes `Stahovac` (zdroj `cnb_kurzy`).
* **Výjimky** v `core.normalizace_vyjimka` (pouze INSERT, jedna na záznam, druh a pole), běhy v
  `core.normalizace_beh`. **Pokrytí** plátců (zadavatel/poskytovatel × zdroj, od kdy) je pohled `core.pokryti_platcu`.
**Důsledky.** Zápis do core jde výhradně přes `core.zapis_verzi()` (hromadně `pvk.core.zapis_entity`, klíče z
přirozených klíčů, D-015), opakovaný běh nic nezdvojí. Registr smluv se normalizuje, až bude v raw (D-040).
Poskytovatele u seznamu operací (řídicí orgán) a u IS ReD (tabulka rozhodnutí) zdroj v raw zatím neuvádí jako IČO –
tok má plátce neurčeného s důvodem.

## D-042 Tabulka limitů ZZVZ s platností a zdrojem

**Rozhodnutí.** Limity VZMR (§ 27) a minimální lhůty podle druhu řízení (§ 54, § 57, § 58, JŘSU) jsou
v `metodika/limity-zzvz-2026.09.json` a v `core.limit` (bitemporálně, `pravni_zaklad` = ustanovení + URL + datum
ověření). Ověřeno 26. 9. 2026 z aktuálního znění zákona č. 134/2016 Sb. na zakonyprolidi.cz (znění
03.04.2025–31.12.2026), proto platnost `[2025-04-03, 2027-01-01)`. Dřívější znění nejsou bez přihlášení dostupná;
hodnoty před 3. 4. 2025 ani přesné datum změny limitů VZMR se proto nezapisují, dokud nebudou ověřeny z veřejného
zdroje (e-Sbírka). Hranice VZMR platí včetně („rovna nebo nižší“).

## D-043 D-039 vynuceno publikační bránou

**Rozhodnutí.** Brána `pvk.publikace` odmítne dotační údaj (částka/souhrn/indikátor dotačního typu nebo z dotačního
zdroje) bez platného data v poli `stav_k_datu` (`DOTACE_BEZ_STAVU_K_DATU`); testy v
`tests/test_publikacni_podminky.py`. V databázi: `ind.*.stav_dat_k` a pohledy `ind.*_k_publikaci` dotační výsledek
bez něj nevydají (migrace 0008), `core.castka.stav_dat_k` je u dotačních částek povinný (migrace 0009).

## D-044 Tok = zakázka, nebo část zakázky; oprava bez mazání

**Kontext.** Kontrola počtu toků (blok 3/2): 18 986 toků `verejna_zakazka` nevzniklo z 5 364 formulářů VVZ – je to
součet dvou zdrojů: VVZ 3 932 toků (= 3 932 různých evidenčních čísel zakázek, formuláře téže zakázky už byly
navázané na jeden tok přes `tok_zdroj`) a seznam operací 15 054 (veřejné zakázky v projektech, řádek = smlouva).
Tok ale nerozlišoval části zakázky: zakázka s více částmi měla jeden tok s „více příjemci“.
**Rozhodnutí.**
* Tok VVZ = zakázka (evidenční číslo); má-li zakázka podle detailu formuláře více částí (BT-137-Lot), je tokem
  každá část (`vvz:<zakázka>:<LOT>`) s dodavatelem z vítězné nabídky části, BT-27-Lot, BT-720 a smlouvou části.
  Všechny formuláře zakázky se navazují na toky jejích částí (doloženě, evidenční číslo; identifikátor NIPEZ
  spojení potvrzuje – 505 identifikátorů, žádný nespojuje různá evidenční čísla). Události celé zakázky mají prázdný
  `tok_id` a k částem vedou přes zdrojový záznam.
* **Oprava bez mazání:** entita, kterou dnešní normalizace z týchž zdrojových záznamů už nevytváří (tok celé
  zakázky nahrazený toky částí, jeho vazby, částky a události), se logicky ukončí funkcí `core.ukonci_entitu()`
  (migrace 0011): aktuální verze dostane `recorded_to = now()` a žádného nástupce, řádky zůstávají, důvod a náhrada
  jsou v `core.ukonceni_entity` (pouze INSERT). Dotaz „jak jsme to věděli v čase T“ vrací původní stav.
**Důsledky.** VVZ má 4 105 toků: 3 862 zakázek bez dělení + 243 částí 70 zakázek (ukončeno 70 toků celých zakázek,
225 vazeb, 201 částek, 2 události). Seznam operací nemá identifikátor zakázky; 15 054 řádků odpovídá 13 140 různým
dvojicím (projekt, název zakázky, dodavatel) – spojení řádků by bylo heuristické, proto zůstává řádek = smlouva
(část) a jde o otevřený bod.

## D-045 Párování smlouva – zakázka

**Rozhodnutí.** `pvk.parovani`, parametry `metodika/parovani-2026.09.json` (stanovené před měřením; RS v raw zatím
jen jako vývojový vzorek). Doložená shoda (skóre 1): `odkaz_bt151` (BT-151 odkazuje na záznam RS) nebo
`ev_cislo_v_rs` (evidenční číslo zakázky / identifikátor NIPEZ v metadatech či textu smlouvy a shoda IČO zadavatele).
Pravděpodobná (jen při shodě IČO zadavatele i dodavatele se stranami smlouvy): 0,4 + 0,25 × datum (lineárně v okně
±30 dní) + 0,25 × částka (tolerance 10 %, přepočet s DPH 21/12 %) + 0,1 × předmět (Jaccard slov bez diakritiky,
plná shoda od 0,5), práh 0,70, maximum 0,999. Oproti pilotu (D-018) přibyl předmět; váhy data a částky se snížily
z 0,3 na 0,25, aby součet zůstal 1. Shody se zapíší do `core.tok_zdroj` (stav, skóre, metoda), až bude RS v core;
propojení je případ se stavem shody, nikdy tok (D-026).

## D-046 Souhrny: jeden zdroj, jeden typ částky, podíl heuristiky a rozpětí

**Rozhodnutí.** `pvk.souhrny.souhrn_subjektu()` sčítá jen přes `core.soucet()` částky jednoho typu, měny, režimu DPH
a periody u toků subjektu (plátce/příjemce) v jednom zdroji (VVZ = souhrn + detail). Vrací pokrytí (toky subjektu,
s částkou daného typu, s IČO obou stran) a podíl objemu částek ze záznamů navázaných jen pravděpodobnou vazbou.
Nad zveřejněným prahem (`metodika/souhrny-2026.09.json`, `prah_podilu_heuristiky_pro_rozpeti` = 0,05) vrací
rozpětí: dolní mez se shodou (pravděpodobné duplicity odečtené), horní bez ní. Publikační brána odmítne souhrn bez
podílu heuristiky (`SOUHRN_BEZ_PODILU_HEURISTIKY`) a nad prahem souhrn bez rozpětí (`SOUHRN_BEZ_ROZPETI`).

## D-047 Historie limitů z e-Sbírky; oprava čísel paragrafů

**Rozhodnutí.** Znění zákona č. 134/2016 Sb. od 1. 10. 2016 do 31. 12. 2026 ověřena v e-Sbírce (strojové rozhraní
webu `e-sbirka.gov.cz/sbr-cache/dokumenty-sbirky/…`, stažení přes `Stahovac`, zdroj `esbirka`). VZMR: 2 000 000 /
6 000 000 Kč v zněních 1. 10. 2016 – 2. 4. 2025, 3 000 000 / 9 000 000 Kč od 3. 4. 2025. Lhůty (§ 54, § 57, § 59,
§ 62) jsou ve všech zněních beze změny. Oprava D-042: lhůty užšího řízení jsou v § 59 (ne § 58), JŘSU v § 62.
Limit je v `core.limit` jedna entita na kód s verzemi platnosti (valid time); entity dřívějšího klíčování
(kód + datum) se ukončily podle D-044.

## D-048 Oprava formou nové verze (včetně intervalu platnosti)

**Kontext.** `core.zapis_verzi()` zachová zbytek starého intervalu před novým začátkem platnosti, takže chybný
začátek (tok s datem 0202-04-23, částky s roky 0202 a 0205) zůstal aktuální. Evidence náhrad u 11 limitů
(`core.ukonceni_entity.nahrazeno`) byla chybná a evidence je pouze INSERT.
**Rozhodnutí.** `core.oprav_entitu(tabulka, klíč, verze, důvod)` (migrace 0012, Python `pvk.core.oprav_entitu`):
uzavře všechny aktuální verze entity a vloží opravené verze s libovolnými intervaly; původní i opravený stav a
důvod zapíše do `core.oprava` (pouze INSERT). Stejný stav podruhé nic nezapíše. Opravu údaje v evidenci, která je
pouze INSERT, zapisuje `core.oprav_zaznam()` do `core.oprava`; pohled `core.ukonceni_entity_opravene` ji uplatní.
Nic se nemaže, historie („jak jsme to věděli v čase T“) zůstává.
**Provedeno 26. 9. 2026:** tok `b4b993b4…` a částky `953e2606…`, `b3e4d917…` mají jedinou aktuální verzi od
náhradního data (žádná aktuální verze před rokem 1990); 11 záznamů evidence náhrad limitů opraveno (každý limit
nahrazen entitou téhož kódu).

## D-049 Párování smlouva–zakázka do výstupů jen po ověření

**Rozhodnutí.** Dokud váhy a práh párování (D-045) nejsou ověřené na registru smluv, párování nesmí vstoupit do
žádného výstupu. `metodika/parovani-2026.09.json` má `"overeno": false`; publikační brána odmítne výstup se shodou,
metodou nebo metodikou párování i souhrn s nenulovým podílem heuristické deduplikace (`PAROVANI_NEOVERENE`),
testy v `tests/test_publikacni_podminky.py`. Ověření = měření na vzorku registru smluv (oficiální zdroj) s ručně
potvrzenými shodami; teprve pak nová verze metodiky s `"overeno": true`.
**Stav 26. 9. 2026:** neověřeno (registr smluv z cloudu nedostupný, ze zrcadla jen 14 smluv vývojového vzorku).

## D-050 Indikátory v1: povinné údaje, minimální základ, čekající na zdroj

**Rozhodnutí.** Každý výsledek v `ind.indikator_vysledek` nese období, počet případů, základ, srovnávací skupinu
(nový sloupec, pro nové řádky povinný spolu se základem – migrace 0012) a verzi metodiky
(`metodika/ind-<kód>-2026.09.json`, popis `metodika/indikatory-2026.09.md`); pod `min_pocet_pripadu` výsledek
nevznikne. Spočítané: koncentrace dodavatele, jediná nabídka, zkrácené lhůty, opakovaný příjemce, nový subjekt.
Čekající na zdroj (`"stav": "ceka_na_zdroj"`, funkce a testy na vzorových datech, na skutečných datech se
nepočítají, brána výsledky odmítne – `INDIKATOR_CEKA_NA_ZDROJ`): dělení pod limit (registr smluv), dodavatel ve
sledovaném pásmu kotvy, změna struktury v okně (OR z kotvy). Závislost na veřejných penězích se ve v1 nevydává (D-027).
Nový subjekt: datum vzniku z kotvy (ARES), přeměna podle „ostatních skutečností“ v záznamu OR (fúze, rozdělení,
odštěpení, nástupnictví, změna právní formy) – subjekt vzniklý přeměnou nový není, bez záznamu OR se nehodnotí.

## D-051 Prahy indikátorů: jen návrh

**Rozhodnutí.** `docs/prahy_navrh.md` obsahuje rozložení hodnot ve srovnávacích skupinách a návrh prahů
(p90, u počtů p95, skupinově jen při n ≥ 30). Prahy **nejsou schválené**; schvaluje je vlastník metodiky
a zapíší se novou verzí metodiky před dalším měřením (D-020, D-029).

## D-052 Prahy: metoda v0.9 schválena, hodnoty ne

**Rozhodnutí (vlastník metodiky, 26. 9. 2026).** Metoda z `docs/prahy_navrh.md` – 90. percentil (podíly), 95. percentil
(počty), skupinově od 30 výsledků, jinak celkový práh – je prozatímní metodika v0.9 (`metodika/prahy-0.9.json`).
Konkrétní hodnoty **nejsou schválené**; přepočítají se a schválí na nejméně 12 měsících dat.
**Důsledky.** `"hodnoty_schvaleny": false`; publikační brána odmítne výsledek označený jako nad prahem nebo nesoucí
hodnotu prahu (`nad_prahem`, `prah`, `oznaceni_prahu` → `PRAH_NESCHVALEN`), dokud všechny verze metodiky prahů
neuvádějí schválené hodnoty. Testy v `tests/test_publikacni_podminky.py`.

## D-053 Nové verze metodik: nový subjekt a zkrácené lhůty; stav metodiky v bráně

**Rozhodnutí.**
* Nový subjekt (`ind-novy-subjekt-2026.09.2`): **stáří subjektu v den toku** – dny od vzniku podle kotvy k datu
  uzavření smlouvy k toku (jinak začátku platnosti toku); každý tok se hodnotí sám, bez historie prvního toku;
  přeměny (ostatní skutečnosti v OR) dál nejsou nový subjekt. Zdroje VVZ a seznam operací (zakázky v projektech).
* Zkrácené lhůty (`ind-zkracene-lhuty-2026.09.2`): zákonná zkrácení podle e-Sbírky (znění 3. 4. 2025 – 31. 12. 2026):
  podlimitní otevřené řízení až o 5 pracovních dnů při předběžném oznámení (§ 54 odst. 4), nadlimitní otevřené
  řízení na dodávky a služby na 15 dnů při předběžném oznámení nebo naléhavosti (§ 57 odst. 2); příznaky eForms
  BT-125(i)-Lot a BT-106-Procedure. Neověřuje se časový odstup předběžného oznámení a prodloužení podle § 57 odst. 1.
* Předchozí verze mají stav `nahrazena`. Pohled `ind.indikator_k_publikaci` (migrace 0013) i brána nevydají výsledky
  metodiky ve stavu `ceka_na_zdroj`, `neuplna_metodika` nebo `nahrazena` (`INDIKATOR_METODIKA_NAHRAZENA`,
  `INDIKATOR_NEUPLNA_METODIKA`). Staré výsledky zůstávají v `ind` (pouze INSERT).

## D-054 Názvosloví: „rizikové pásmo“ podle kotvy; brána hlídá výstupní texty

**Rozhodnutí.** Čekající indikátor se jmenuje jako pojem kotvy: `rizikove_pasmo` (metodika `ind-rizikove-pasmo-2026.09`;
dříve „dodavatel ve sledovaném pásmu kotvy“, D-050). Brána kontroluje hodnotící výrazy jen ve výstupních textech
(pole `text` výstupů a textové výstupní soubory), ne v interních názvech (kódy indikátorů, metodik, funkce); interní
názvy dnes neblokovala a kontrola výstupů se nemění – „rizikový dodavatel“ ve výstupním textu dál neprojde (test
`test_interni_nazvy_neblokuji_kontrola_textu_zustava`).

## D-055 Kontrolní sada, rozhraní pro kotvu, předání

**Rozhodnutí.** `docs/kontrolni_sada.csv` (`python -m pvk.kontrolni_sada`): případy podle skupin metodiky z dostupných
dat (zakázky s částmi, zrušená řízení, dotace se stavem k datu, cizí měna, subjekty po přeměně – jen právnické osoby,
strany bez IČO – jen názvy vynechaných polí), sloupec `potvrzeno` vyplní člověk; skupiny registru smluv „čeká na
zdroj“. Rozhraní pro kotvu: schéma `pvk.verejne_penize` 1.0 (`docs/rozhrani_kotva.md`, `pvk.rozhrani`). Předání
a postup prvního spuštění: `docs/stav.md`. Nové dokumenty kontroluje publikační brána.
