# Metodika indikátorů 2026.09 (blok 4)

Indikátor je **signál k prověření, nikdy zjištění**. Každý výsledek (`ind.indikator_vysledek`) nese období,
počet případů, základ, srovnávací skupinu a verzi metodiky (`metodika/ind-<kód>-2026.09.json`); pod minimálním
základem (`min_pocet_pripadu`) výsledek nevznikne. Počítá se vždy v rámci jednoho zdroje (D-026). Prahy
pro zvýraznění nejsou schválené – návrh je v `docs/prahy_navrh.md`.

| indikátor | hodnota | počet případů / základ | srovnávací skupina | min. |
|---|---|---|---|---:|
| koncentrace_dodavatele | podíl největšího dodavatele na objemu zadavatele (jeden typ částky, bez DPH, CZK) | zakázky / objem | zdroj + velikost objemu zadavatele | 5 |
| jedina_nabidka | podíl výsledků (částí) s jedinou nabídkou (BT-759, BT-760 = tenders) | výsledky se známým počtem nabídek | oddíl CPV (2 číslice) | 5 |
| zkracene_lhuty | podíl otevřených řízení s lhůtou (BT-131) kratší než zákonné minimum platné v den zahájení (`core.limit`) | otevřená řízení | druh limitu (režim, povaha) | 5 |
| opakovany_prijemce | počet dotací příjemce ve zdroji; stav k datu zdroje (D-039) | dotace / přiznaný objem | zdroj | 2 |
| novy_subjekt | stáří dodavatele (dny od vzniku podle kotvy) při první smlouvě ve VVZ; ≤ 365 dní | smlouvy / stáří | dodavatelé se smlouvou ve VVZ | 1 |

Zkrácené lhůty: nadlimitní režim = formulář odeslaný do TED; lhůta v kalendářních dnech (nadlimitní) nebo
pracovních dnech (podlimitní, bez víkendů a svátků ČR); zákonná zkrácení (předběžné oznámení, § 57 odst. 2)
se nezohledňují, proto jde jen o signál. Nový subjekt: datum vzniku z kotvy, subjekt vzniklý přeměnou (fúze,
rozdělení, změna právní formy podle „ostatních skutečností“ v OR) nový není; bez dostupného záznamu OR se
nehodnotí. Fyzické osoby se nikdy nezobrazují (pravidlo 4).

**Čekají na zdroj** (funkce a testy na vzorových datech, na skutečných datech se nepočítají, brána výsledky
nepustí): dělení pod limit (registr smluv), dodavatel ve sledovaném pásmu kotvy (kotva), změna struktury
v okně (obchodní rejstřík z kotvy). Závislost na veřejných penězích se ve v1 nevydává (D-027).
