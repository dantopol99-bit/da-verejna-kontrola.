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
