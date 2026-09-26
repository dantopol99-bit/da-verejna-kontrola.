# Blok 3 – normalizace a tok: měření

Stav k 26. 09. 2026. Vygenerováno `python -m pvk.normalizace` (make normalizace) nad vývojovými vzorky v raw; čísla popisují vzorek a běh normalizace, ne celé zdroje.

## Vzorky v raw

| zdroj | záznamů v raw | z toho vývojový vzorek | poslední běh sběru |
|---|---:|---:|---|
| dotaceeu_2127 | 48692 | 0 | uspech |
| hlidac_statu_rs | 14 | 14 | nedokonceno |
| red | 68 | 0 | uspech |
| registr_smluv | 0 | 0 | preskoceno |
| vvz | 5364 | 0 | uspech |
| vvz_detail | 683 | 0 | uspech |

## Toky podle typu (aktuální verze v core)

| zdroj | druh toku | toků | s určeným plátcem i příjemcem |
|---|---|---:|---:|
| dotaceeu_2127 | verejna_zakazka | 15054 | 11762 (78.1 %) |
| dotaceeu_2127 | dotace | 40935 | 0 (0.0 %) |
| red | dotace | 23 | 0 (0.0 %) |
| vvz | verejna_zakazka | 4105 | 323 (7.9 %) |
| vvz_detail | verejna_zakazka | 765 | 323 (42.2 %) |

Celkem: verejna_zakazka 19159, dotace 40958.

## Částky: podíl s určeným typem (cíl 100 %)

Rámec: částky nalezené ve zdroji = částky zapsané v core (vždy s typem) + částky, které nešlo typovat (výjimky `castka_bez_meny`, `castka_bez_pravidla_metodiky`).

| zdroj | částek ve zdroji | s typem, DPH, měnou a periodou | podíl |
|---|---:|---:|---:|
| dotaceeu_2127 | 162898 | 162898 | 100.0 % |
| red | 23 | 23 | 100.0 % |
| vvz_detail | 1104 | 1104 | 100.0 % |

Částky v core podle typu (aktuální verze):

| typ | měna | přepočet | počet |
|---|---|---|---:|
| predpokladana | CZK | neni_treba | 15222 |
| predpokladana | EUR | kurz_cnb | 389 |
| predpokladana | PLN | kurz_cnb | 38 |
| predpokladana | USD | kurz_cnb | 1 |
| vysoutezena | CZK | neni_treba | 370 |
| vysoutezena | EUR | kurz_cnb | 2 |
| smluvni | CZK | neni_treba | 14633 |
| smluvni | EUR | kurz_cnb | 383 |
| smluvni | PLN | kurz_cnb | 38 |
| zmena_dodatkem | CZK | neni_treba | 137 |
| dotace_priznana | CZK | neni_treba | 80297 |
| dotace_cerpana | CZK | neni_treba | 52515 |

Částek v core bez typu, režimu DPH, měny nebo periody: 0 (databáze je nepřijme).

## IČO: podíl nespárovaných podle zdroje

Rámec: různé hodnoty IČO uvedené ve zdroji (tento běh). Nespárované = neplatné (formát, modulo 11) nebo nenalezené v kotvě (ARES).

| zdroj | IČO ve zdroji | neplatná | nenalezená v kotvě | nespárovaná celkem | podíl |
|---|---:|---:|---:|---:|---:|
| dotaceeu_2127 | 24215 | 1017 | 131 | 1148 | 4.7 % |
| red | 22 | 0 | 0 | 0 | 0.0 % |
| vvz | 1168 | 1 | 0 | 1 | 0.1 % |
| vvz_detail | 711 | 0 | 6 | 6 | 0.8 % |

## Výjimky

| zdroj | druh výjimky | počet |
|---|---|---:|
| dotaceeu_2127 | datum_neplatne | 2 |
| dotaceeu_2127 | ico_nenalezeno_v_kotve | 169 |
| dotaceeu_2127 | ico_neplatna_kontrolni_cislice | 35 |
| dotaceeu_2127 | ico_neplatny_format | 3136 |
| vvz | ico_neplatny_format | 1 |
| vvz_detail | ico_nenalezeno_v_kotve | 20 |

Výjimek celkem: 3363 (tabulka `core.normalizace_vyjimka`).

## Události

| typ | počet |
|---|---:|
| zahajeni_rizeni | 15047 |
| uzavreni_smlouvy | 15668 |
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

V `core.limit` je 13 limitů (VZMR a minimální lhůty, zdroj u každého v `pravni_zaklad`, viz `metodika/limity-zzvz-2026.09.json`).

## Blok 3/2 – kontrola počtu toků a deduplikace (26. 9. 2026, doplněno ručně)

### Proč 18 986 toků `verejna_zakazka` (stav po 1. části)

Nešlo o tok za formulář. Číslo je součet dvou zdrojů:

| zdroj | záznamů | toků | jednotka toku |
|---|---:|---:|---|
| VVZ (souhrn + detail) | 5 364 formulářů + 683 detailů | 3 932 | zakázka (evidenční číslo; 3 932 různých čísel) |
| seznam operací 21+ | 15 054 řádků se zakázkou | 15 054 | smlouva (část) v projektu |

**Oprava (D-044).** Zakázka rozdělená na části je teď tok za každou část. Podle 683 detailů má více částí
70 zakázek (243 částí: 28× 2, 20× 3, 6× 4, 5× 5, 11× 6 a více). Opravu zapsala nová normalizace:
70 toků celých zakázek bylo logicky ukončeno (`core.ukonci_entitu`, nic se nesmazalo) a nahrazeno 243 toky částí.
Spolu s nimi se ukončilo 225 vazeb a 201 částek, které nové vazby a částky částí nahradily.

VVZ teď má **4 105 toků** (3 862 zakázek bez dělení a 243 částí). Celkem je 19 159 toků `verejna_zakazka`.
Seznam operací nemá identifikátor zakázky. 15 054 řádků odpovídá 13 140 různým trojicím (projekt, název
zakázky, dodavatel); zbylé řádky jsou dodatky nebo víc smluv téhož dodavatele. Jejich spojení by bylo
heuristické, proto zůstává otevřeným bodem.

### Deduplikace uvnitř VVZ (doložená)

* Formuláře téže zakázky spojuje evidenční číslo zakázky. Identifikátor NIPEZ (505 v detailech) spojení
  potvrzuje: žádný nespojuje dvě různá evidenční čísla a související formuláře mají vždy stejné číslo zakázky.
* Formulářů na zakázku: 1 → 3 248 zakázek, 2 → 439, 3 → 112, 4 → 51, 5 → 27, 6 a více → 55.
* Zakázek s více částmi je 70 z 3 932 (jen tam, kde je stažený detail; detail je stažen u 683 z 5 364 formulářů).

### Párování smlouva–zakázka (D-045)

* Pravidla jsou otestovaná na vzorových datech (`tests/test_parovani.py`, 10 testů): doložená shoda přes
  BT-151 i přes evidenční číslo, pravděpodobná shoda se skóre pod 1, přepočet DPH, práh, předmět bez diakritiky.
* Registr smluv jsem 26. 9. zkusil jednou. Oficiální data byla nedostupná. Zrcadlo odpovědělo a stihlo
  14 smluv (vývojový vzorek), než test ukončil 90sekundový limit.
* 618 smluv z oznámení o výsledku VVZ proti 14 smlouvám zrcadla: 0 shod. U 8 smluv je zadavatel zároveň
  zadavatelem ve VVZ, ale vzorek je příliš malý na měření. Do `core.tok_zdroj` se shody zapíší, až bude
  registr smluv v core.

### Souhrny (D-046)

`pvk.souhrny.souhrn_subjektu()` počítá objem jen v rámci jednoho zdroje a typu částky. Vrací pokrytí a podíl
heuristické deduplikace. Nad prahem 5 % vrací rozpětí: dolní mez se shodou, horní bez ní. Všechny vazby
v core jsou zatím doložené, takže podíl heuristiky je u skutečných dat 0. Publikační brána odmítne souhrn bez
podílu i souhrn nad prahem bez rozpětí (`tests/test_souhrny.py`).

### Opakovaný běh nad skutečnou databází

* **1. opakovaný běh** (VVZ + seznam operací): nový tok ani nová vazba nevznikly. Nové verze vznikly jen při
  známé opravě data 0202-04-23 (1 tok: 2 řádky, 2 částky: 4 řádky) a 2 entity se ukončily.
* **2. opakovaný běh:** počty řádků ve všech tabulkách core se nezměnily (tok 61 020, tok_zdroj 70 500,
  částka 164 205, událost 79 312, entita 452 183).
* **Známé omezení:** starý tok s datem 0202 má dál aktuální verzi pro interval [0202-04-23, 2026-06-24).
  `zapis_verzi` upravuje jen nový interval; oprava chybného začátku platnosti potřebuje samostatnou funkci
  (otevřený bod).

### IS ReD

Dostaženo za 8 minut: 23 dotací, 22 příjemců a 23 rozhodnutí. Po normalizaci má všech 23 toků příjemce a
23 částek `dotace_priznana` se stavem k datu exportu 21. 2. 2026. Poskytovatel je v IS ReD jen položka
číselníku bez IČO, takže plátce zůstává neurčený.

### Limity (D-047)

Historie z e-Sbírky: VZMR 2 000 000 / 6 000 000 Kč platí v zněních 1. 10. 2016 – 2. 4. 2025, od 3. 4. 2025
platí 3 000 000 / 9 000 000 Kč. Lhůty jsou ve všech zněních od 1. 10. 2016 beze změny. Opravena čísla
paragrafů: užší řízení § 59, JŘSU § 62.

### Otevřené body

1. **Seznam operací:** spojit řádky téže zakázky, až bude k dispozici identifikátor; název a dodavatel by
   dávaly jen heuristickou shodu.
2. **Oprava chybného začátku platnosti** (tok s datem 0202): potřebuje funkci pro úpravu celého intervalu.
3. **Detail VVZ je stažen jen z části** (683 z 5 364): u zbylých zakázek se části zatím nerozlišují. Rozliší
   je další běh `make sber` a normalizace.
4. **Registr smluv v core:** normalizace RS a zápis shod do `core.tok_zdroj`, až bude oficiální zdroj
   dostupný. Zrcadlo smí sloužit jen jako vývojový vzorek.
5. **Evidence ukončených limitů:** u 11 limitů ukončených v tomto běhu je v `core.ukonceni_entity.nahrazeno`
   uvedena jen první náhradní entita (chyba skriptu, opravena). Evidence je pouze INSERT, záznamy zůstávají.
