# Metodika normalizace 2026.09 (raw -> core)

Parametry: `metodika/normalizace-2026.09.json`. Rozhodnutí: D-041 (normalizace), D-040 (vývojový vzorek),
D-042 (limity), D-039/D-043 (stav k datu u dotací).

## Typ částky podle pole zdroje

| zdroj | pole | typ | DPH | perioda |
|---|---|---|---|---|
| VVZ (eForms) | BT-27 předpokládaná hodnota | predpokladana | bez DPH (definice eForms) | celkem |
| VVZ (eForms) | BT-720 hodnota vybrané nabídky, jinak BT-161 hodnota výsledku | vysoutezena | bez DPH | celkem |
| VVZ (eForms), formuláře 38–40 | hodnota v oznámení o změně smlouvy | zmena_dodatkem | bez DPH | celkem |
| seznam operací 21+ | právní akt: příspěvek Unie, národní veřejné zdroje | dotace_priznana | mimo DPH | celkem |
| seznam operací 21+ | vyúčtováno v žádostech o platbu: příspěvek Unie, národní veřejné zdroje | dotace_cerpana | mimo DPH | celkem |
| seznam operací 21+ | předpokládaná hodnota VZ bez DPH | predpokladana | bez DPH | celkem |
| seznam operací 21+ | cena VZ podle smlouvy/dodatku bez DPH | smluvni | bez DPH | celkem |

Soukromé zdroje a celkové způsobilé výdaje nejsou veřejné peníze a nezapisují se. Částka bez pravidla nebo bez
měny se nezapíše a je výjimkou (`castka_bez_pravidla_metodiky`, `castka_bez_meny`). Dotační částky nesou
`stav_dat_k` (datum souboru zdroje).

## IČO

8 číslic po doplnění úvodních nul, kontrolní číslice modulo 11. Neplatné -> výjimka
(`ico_neplatny_format`, `ico_neplatna_kontrolni_cislice`). IČO neznámé platformě se ověří v kotvě; nenalezené ->
`ico_nenalezeno_v_kotve`. Nespárované IČO = neplatné nebo nenalezené v kotvě.

## Kurzy

Kurz ČNB vyhlášený nejpozději v den uzavření (u dotací den podpisu právního aktu), nejvýš 10 dní starý;
přepočet `hodnota × kurz` na haléře. Bez kurzu příznak `kurz_nedostupny` a výjimka.

## Tok a vazby

Tok v rámci jednoho zdroje, klíč podle identifikátoru ve zdroji (D-041). Vazba zdrojového záznamu na tok je
doložená (skóre 1). Plátce/příjemce bez ověřeného IČO -> `subjekt_neurcen_duvod`.
