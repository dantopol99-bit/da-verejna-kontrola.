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
