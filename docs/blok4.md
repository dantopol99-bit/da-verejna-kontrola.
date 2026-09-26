# Blok 4 – indikátory: měření

Stav k 26. 9. 2026. Data: vývojové vzorky v core (VVZ formuláře 26. 8. – 25. 9. 2026, detail eForms 1 701 z 5 364;
seznam operací 21+ 09/2026; IS ReD 23 dotací, stav k 21. 2. 2026). Indikátor je signál k prověření, nikdy
zjištění. Prahy nejsou schválené (návrh: `docs/prahy_navrh.md`). Podrobná rozložení: `docs/blok4_indikatory.json`.

## 0. Korekce (D-048)

`core.oprav_entitu()` opravila tok s datem 0202-04-23 a dvě částky (roky 0202 a 0205). Žádná aktuální verze
v core teď nezačíná před rokem 1990. Evidenci náhrad u 11 limitů opravuje 11 záznamů v `core.oprava`,
pohled `core.ukonceni_entity_opravene` uvádí 11 různých náhrad. Opakovaná oprava nic nezapíše.

## 1. Párování (D-049)

Stav: **neověřeno**. Brána odmítne každý výstup s párováním smlouva–zakázka (`PAROVANI_NEOVERENE`),
včetně souhrnu s nenulovým podílem heuristické deduplikace.

## 2. Detail VVZ

Detail se stahoval 6 minut s navazováním: 1 018 nových formulářů, celkem 1 701 z 5 364, zbývá 3 663.
Normalizace našla další zakázky s více částmi. VVZ má teď 4 398 toků a 154 toků celých zakázek je nahrazeno
toky částí (D-044).

## 3. Indikátory spočítané na skutečných datech

| indikátor | kandidátů | min. základ | výsledků nad minimem (v `ind`) | p50 | p90 |
|---|---:|---:|---:|---:|---:|
| koncentrace_dodavatele | 3866 | 5 | 378 | 0,50 | 0,87 |
| jedina_nabidka | 431 | 5 | 42 | 0,41 | 0,88 |
| zkracene_lhuty | 174 | 5 | 9 | 0,17 | 0,26 |
| opakovany_prijemce | 19194 | 2 | 11404 | 2,00 | 4,00 |
| novy_subjekt | 569 | 1 | 569 | 9093,00 | 12421,20 |

Každý výsledek má období, počet případů, základ, srovnávací skupinu a verzi metodiky. Kontrola v databázi:
0 výsledků bez základu nebo skupiny a 0 s hodnotícími výrazy (`ind.obsahuje_hodnotici_slova`).
Pohled `ind.indikator_k_publikaci` vydá všechny výsledky kromě 10 výsledků opakovaného příjemce bez stavu
k datu (příjemce bez přiznané částky, D-039).

* **koncentrace_dodavatele:** klouzavé okno 36 měsíců (09/2023–09/2026), zvlášť VVZ (vysoutěžená cena) a seznam
  operací (smluvní cena). Srovnávací skupina = zdroj + velikost objemu zadavatele.
* **jedina_nabidka:** jen výsledky se známým počtem nabídek (BT-759/BT-760), skupina = oddíl CPV.
* **zkracene_lhuty:** otevřená řízení, zákonné minimum z `core.limit` platné v den zahájení. U podlimitních
  řízení se počítají pracovní dny se svátky ČR. Nad minimálním základem vyšlo jen 9 zadavatelů.
* **opakovany_prijemce:** 11 403 příjemců ze seznamu operací a 1 z IS ReD. Fyzické osoby se vynechávají.
* **novy_subjekt:** 569 dodavatelů (právnických osob) se smlouvou ve VVZ. Nejmladší měl při první smlouvě
  víc než 365 dní od vzniku, takže 0 dodavatelů je do 365 dní. Přeměna se ověřuje v záznamu OR.

## 4. Indikátory čekající na zdroj

Dělení pod limit, dodavatel ve sledovaném pásmu kotvy a změna struktury v okně mají funkce otestované
na vzorových datech (`tests/test_indikatory.py`). Na skutečných datech se nepočítají, stav je `ceka_na_zdroj`
a brána jejich výsledky odmítne. Závislost na veřejných penězích se ve v1 nevydává (D-027).

## 5.–6. Prahy a texty

Návrh prahů (p90 / p95) je v `docs/prahy_navrh.md` a není schválený. Texty indikátorů prošly kontrolou
hodnotících výrazů v testech i v databázi. `docs/blok4.md` a `docs/prahy_navrh.md` kontroluje publikační brána.

## Zbývá

1. **Detail VVZ:** stáhnout zbylých 3 663 formulářů, pak přepočítat jedinou nabídku, zkrácené lhůty
   a nový subjekt.
2. **Zkrácené lhůty:** zohlednit zákonná zkrácení (předběžné oznámení) a užší řízení, kde lhůta běží od výzvy.
3. **Opakovaný příjemce:** stav k datu i u příjemců bez přiznané částky (z data souboru či exportu zdroje).
4. **Schválení prahů** vlastníkem metodiky, pak nová verze metodik.
