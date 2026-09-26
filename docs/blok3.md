# Blok 3 – normalizace a tok: měření

Stav k 26. 09. 2026. Vygenerováno `python -m pvk.normalizace` (make normalizace) nad vývojovými vzorky v raw; čísla popisují vzorek a běh normalizace, ne celé zdroje.

## Vzorky v raw

| zdroj | záznamů v raw | z toho vývojový vzorek | poslední běh sběru |
|---|---:|---:|---|
| dotaceeu_2127 | 48692 | 0 | uspech |
| hlidac_statu_rs | 0 | 0 | preskoceno |
| red | 23 | 0 | nedokonceno |
| registr_smluv | 0 | 0 | preskoceno |
| vvz | 5364 | 0 | uspech |
| vvz_detail | 683 | 0 | uspech |

## Toky podle typu (aktuální verze v core)

| zdroj | druh toku | toků | s určeným plátcem i příjemcem |
|---|---|---:|---:|
| dotaceeu_2127 | verejna_zakazka | 15054 | 11762 (78.1 %) |
| dotaceeu_2127 | dotace | 40935 | 0 (0.0 %) |
| red | dotace | 23 | 0 (0.0 %) |
| vvz | verejna_zakazka | 3932 | 239 (6.1 %) |
| vvz_detail | verejna_zakazka | 592 | 239 (40.4 %) |

Celkem: verejna_zakazka 18986, dotace 40958.

## Částky: podíl s určeným typem (cíl 100 %)

Rámec: částky nalezené ve zdroji = částky zapsané v core (vždy s typem) + částky, které nešlo typovat (výjimky `castka_bez_meny`, `castka_bez_pravidla_metodiky`).

| zdroj | částek ve zdroji | s typem, DPH, měnou a periodou | podíl |
|---|---:|---:|---:|
| dotaceeu_2127 | 162896 | 162896 | 100.0 % |
| vvz_detail | 971 | 971 | 100.0 % |

Částky v core podle typu (aktuální verze):

| typ | měna | přepočet | počet |
|---|---|---|---:|
| predpokladana | CZK | neni_treba | 15088 |
| predpokladana | EUR | kurz_cnb | 388 |
| predpokladana | PLN | kurz_cnb | 38 |
| predpokladana | USD | kurz_cnb | 1 |
| vysoutezena | CZK | neni_treba | 370 |
| vysoutezena | EUR | kurz_cnb | 2 |
| smluvni | CZK | neni_treba | 14632 |
| smluvni | EUR | kurz_cnb | 383 |
| smluvni | PLN | kurz_cnb | 38 |
| zmena_dodatkem | CZK | neni_treba | 138 |
| dotace_priznana | CZK | neni_treba | 80274 |
| dotace_cerpana | CZK | neni_treba | 52515 |

Částek v core bez typu, režimu DPH, měny nebo periody: 0 (databáze je nepřijme).

## IČO: podíl nespárovaných podle zdroje

Rámec: různé hodnoty IČO uvedené ve zdroji (tento běh). Nespárované = neplatné (formát, modulo 11) nebo nenalezené v kotvě (ARES).

| zdroj | IČO ve zdroji | neplatná | nenalezená v kotvě | nespárovaná celkem | podíl |
|---|---:|---:|---:|---:|---:|
| dotaceeu_2127 | 24215 | 1017 | 131 | 1148 | 4.7 % |
| vvz | 1168 | 1 | 0 | 1 | 0.1 % |
| vvz_detail | 711 | 0 | 6 | 6 | 0.8 % |

## Výjimky

| zdroj | druh výjimky | počet |
|---|---|---:|
| dotaceeu_2127 | ico_nenalezeno_v_kotve | 169 |
| dotaceeu_2127 | ico_neplatna_kontrolni_cislice | 35 |
| dotaceeu_2127 | ico_neplatny_format | 3136 |
| vvz | ico_neplatny_format | 1 |
| vvz_detail | ico_nenalezeno_v_kotve | 20 |

Výjimek celkem: 3361 (tabulka `core.normalizace_vyjimka`).

## Události

| typ | počet |
|---|---:|
| zahajeni_rizeni | 15048 |
| uzavreni_smlouvy | 15671 |
| zverejneni | 5364 |
| dodatek | 1175 |
| rozhodnuti_o_dotaci | 40955 |
| zneplatneni | 508 |
| zruseni | 281 |

## Pokrytí zadavatelů a poskytovatelů (`core.pokryti_platcu`)

| zdroj | plátců s IČO | nejstarší tok od |
|---|---:|---|
| dotaceeu_2127 | 4121 | 0202-04-23 |
| vvz | 1092 | 2026-08-26 |
| vvz_detail | 281 | 2026-08-26 |

## Limity

V `core.limit` je 11 limitů (VZMR a minimální lhůty, zdroj u každého v `pravni_zaklad`, viz `metodika/limity-zzvz-2026.09.json`).

## Poznámky k měření (doplněno ručně, 26. 9. 2026)

* **Registr smluv chybí:** oficiální data i zrcadlo Hlídač státu byly nedostupné (server ukončil TLS spojení,
  D-040). Vzorek 300 smluv proto v raw není a toky `smlouva` v core zatím nejsou.
* **IS ReD je neúplné:** v 8minutovém rozpočtu se stihl jen soubor dotací (23 dotací v okně podle dat).
  Příjemci a rozhodnutí (částky) se nestáhli, takže dotace ReD nemají příjemce ani částku.
  Chybějící údaj není nula (D-039).
* **Detail VVZ je stažen jen z části:** 683 z 5 364 formulářů (limit 4 minuty). Proto je u toků VVZ nízký podíl
  toků s určeným příjemcem (dodavatel je jen v detailu výsledku); další běh `make sber` detail doplní.
* **Dotace ze seznamu operací nemají určeného plátce:** zdroj uvádí program, ne IČO řídicího orgánu (D-041).
  Toky mají důvod v `subjekt_neurcen_duvod`.
* **Data mimo rozsah:** jeden tok ze seznamu operací má datum právního aktu `0202-04-23` (chyba ve zdroji).
  Vznikl v prvním běhu, který data ještě nekontroloval. Běhy s novým kódem takové datum nepoužijí a zapíšou
  výjimku `datum_neplatne`. Starou verzi nelze smazat (core je pouze INSERT), opraví ji až příští běh
  novou verzí.
* **Cizí měny:** kurzy ČNB byly dostupné, všech 850 cizoměnových částek je přepočteno (`kurz_cnb`).
  Původní hodnota zůstává.
