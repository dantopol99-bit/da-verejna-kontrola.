# Rozhraní pro kotvu: záložka „Veřejné peníze“ v profilu firmy

Schéma **`pvk.verejne_penize`, verze 1.0**. Výstup vrací `pvk.rozhrani.verejne_penize(conn, ico, k_datu)`
(příkazová řádka: `python -m pvk.rozhrani <IČO> [RRRR-MM-DD]`) jako JSON pro jedno IČO. Kotva (Firemní
databáze) výstup jen zobrazuje; tento repozitář do kotvy nezasahuje a údaje kotvy neukládá. Ven jde jen to,
co projde publikační bránou (`pvk.publikace`); nepropuštěné položky jsou vyjmenované ve `vynechano`.

## Kořen

| pole | typ | povinné | význam |
|---|---|---|---|
| `schema` | string | ano | vždy `pvk.verejne_penize` |
| `schema_verze` | string (semver) | ano | `1.0`; nekompatibilní změna = nová hlavní verze |
| `ico` | string (8 číslic) | ano | IČO subjektu (doplněné nuly, kontrola modulo 11) |
| `k_datu` | date (ISO) | ano | platnost dat ve světě – souhrny a indikátory platné k tomuto dni |
| `stav_poznani` | datetime (ISO, UTC) | ano | čas výpočtu = stav znalosti platformy (transaction time) |
| `vydano` | boolean | ano | `false` = profil se nevydává; pak je vyplněn jen `duvod` |
| `duvod` | string | při `vydano=false` | fyzická osoba / neurčená právní forma (pravidlo 4) nebo IČO v datech nenalezeno (není nula) |
| `obdobi_od`, `obdobi_do` | date | ano | období souhrnů `[od, do)` – 3 roky do `k_datu` |
| `zakazky_jako_zadavatel` | pole Souhrn | ano (i prázdné) | veřejné zakázky, kde je subjekt plátcem |
| `zakazky_jako_dodavatel` | pole Souhrn | ano | veřejné zakázky, kde je subjekt příjemcem |
| `dotace` | pole Souhrn | ano | dotace, kde je subjekt příjemcem |
| `indikatory` | pole Indikátor | ano | publikovatelné výsledky indikátorů (bez prahů – D-052) |
| `vynechano` | pole {polozka, duvod[]} | ano | položky, které brána nepustila (kódy porušení) |
| `upozorneni` | pole string | ano | texty, které kotva zobrazí u záložky |

## Souhrn (vždy jeden zdroj a jeden typ částky – D-026)

| pole | typ | povinné | význam |
|---|---|---|---|
| `zdroj` | string | ano | `vvz`, `dotaceeu_2127`, `red` (později `registr_smluv`) |
| `typ` | enum | ano | typ částky: `predpokladana`, `vysoutezena`, `smluvni`, `zmena_dodatkem`, `dotace_priznana`, `dotace_cerpana`, `vratka` |
| `mena` | string ISO 4217 | ano | měna souhrnu (souhrny jsou v CZK; cizí měna je v core přepočtená kurzem ČNB) |
| `dph_rezim` | enum | ano | `bez_dph`, `vcetne_dph`, `mimo_dph`, `neurceno` |
| `perioda` | enum | ano | `celkem`, `rocni`, `mesicni`, `jednotkova`, `neurcena` |
| `hodnota` | string (decimal) | ano | objem se shodou (pravděpodobné duplicity odečtené) |
| `pocet_castek` | integer | ano | počet sečtených částek |
| `pokryti` | objekt | **ano** | `toku` (toky subjektu ve zdroji), `s_castkou_typu`, `s_ico_obou_stran` |
| `podil_heuristicke_deduplikace` | number 0–1 | **ano** | podíl objemu stojící na pravděpodobných vazbách |
| `rozpeti` | objekt / null | nad prahem | `dolni_se_shodou`, `horni_bez_shody` (D-046) |
| `metodika_verze` | string | ano | např. `souhrny-2026.09` |
| `stav_k_datu` | date | **u dotací ano** | stav dat zdroje (datum exportu/souboru, D-039) |

## Indikátor

`indikator_kod`, `obdobi_od`, `obdobi_do`, `pocet_pripadu`, `zaklad`, `hodnota` (string decimal),
`srovnavaci_skupina`, `metodika_verze`, `text` (popisný, bez hodnotících výrazů), `typ_castky`,
`stav_k_datu` (u dotačních). Hodnota nikdy nenese označení „nad prahem“, dokud hodnoty prahů nejsou schválené
(D-052). Indikátory čekající na zdroj, s neúplnou nebo nahrazenou metodikou se nevydávají.

## Pravidla pro zobrazení v kotvě

1. Každý údaj zobrazit se zdrojem, typem částky a pokrytím; nikdy nesčítat napříč zdroji ani typy.
2. Prázdná sekce = „v datech zdrojů nenalezeno“ (ke `k_datu`), nikdy „žádné veřejné peníze“.
3. Texty indikátorů zobrazovat beze změny (prošly bránou), s upozorněním „signál k prověření“.
4. Profil fyzické osoby se nevydává (`vydano=false`).
