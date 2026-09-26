# Návrh prahů indikátorů (NESCHVÁLENO)

Stav k 26. 9. 2026, metodiky `metodika/ind-*-2026.09.json`. **Prahy zde nejsou schválené** – schvaluje je
vlastník metodiky; do schválení se žádný výsledek neoznačuje jako nad prahem. Prahy se stanovují před
dalším měřením (D-020, D-029) a po schválení se zapíší do nové verze metodiky.

Postup návrhu: rozložení hodnot výsledků nad minimálním základem ve srovnávacích skupinách (percentily
p50/p75/p90/p95, lineární interpolace). Navržený práh = p90 celého rozložení indikátoru (u počtů p95);
skupinový práh se navrhuje jen u skupin s alespoň 30 výsledky, jinak platí celkový. Data jsou vývojový
vzorek (VVZ: formuláře 26. 8. – 25. 9. 2026, detail 1 701 z 5 364; seznam operací 21+ 09/2026; IS ReD 23
dotací), proto jsou percentily jen orientační.

## koncentrace_dodavatele

Hodnota: podíl největšího dodavatele. Výsledků nad minimálním základem (5): 378 (kandidátů 3866).

| srovnávací skupina | n | p50 | p75 | p90 | p95 | navržený práh |
|---|---:|---:|---:|---:|---:|---:|
| dotaceeu_2127: objem nad 100 mil. Kč | 207 | 0,52 | 0,71 | 0,91 | 0,94 | 0,91 |
| dotaceeu_2127: objem 10–100 mil. Kč | 138 | 0,48 | 0,65 | 0,78 | 0,86 | 0,78 |
| vvz: objem 10–100 mil. Kč | 16 | 0,55 | 0,64 | 0,74 | 0,78 | – |
| vvz: objem nad 100 mil. Kč | 9 | 0,46 | 0,52 | 0,64 | 0,78 | – |
| vvz: objem 1–10 mil. Kč | 5 | 0,56 | 0,66 | 0,78 | 0,82 | – |
| dotaceeu_2127: objem 1–10 mil. Kč | 2 | 0,38 | 0,42 | 0,45 | 0,45 | – |
| vvz: objem do 1 mil. Kč | 1 | 0,48 | 0,48 | 0,48 | 0,48 | – |
| **celkem** | 378 | 0,50 | 0,67 | 0,87 | 0,92 | **0,87** |

## jedina_nabidka

Hodnota: podíl výsledků s jedinou nabídkou. Výsledků nad minimálním základem (5): 42 (kandidátů 431).

| srovnávací skupina | n | p50 | p75 | p90 | p95 | navržený práh |
|---|---:|---:|---:|---:|---:|---:|
| CPV 33 | 12 | 0,61 | 0,73 | 0,88 | 0,90 | – |
| CPV 45 | 4 | 0,03 | 0,20 | 0,45 | 0,53 | – |
| CPV 71 | 4 | 0,00 | 0,06 | 0,18 | 0,21 | – |
| CPV 38 | 3 | 0,67 | 0,67 | 0,67 | 0,67 | – |
| CPV 90 | 3 | 0,09 | 0,12 | 0,13 | 0,14 | – |
| CPV 39 | 2 | 0,27 | 0,34 | 0,37 | 0,39 | – |
| CPV 50 | 2 | 0,76 | 0,83 | 0,86 | 0,88 | – |
| CPV 34 | 2 | 0,71 | 0,86 | 0,94 | 0,97 | – |
| CPV 80 | 1 | 0,00 | 0,00 | 0,00 | 0,00 | – |
| CPV 77 | 1 | 0,83 | 0,83 | 0,83 | 0,83 | – |
| CPV 30 | 1 | 0,40 | 0,40 | 0,40 | 0,40 | – |
| CPV 15 | 1 | 0,18 | 0,18 | 0,18 | 0,18 | – |
| CPV 64 | 1 | 0,07 | 0,07 | 0,07 | 0,07 | – |
| CPV 42 | 1 | 0,00 | 0,00 | 0,00 | 0,00 | – |
| CPV 79 | 1 | 0,00 | 0,00 | 0,00 | 0,00 | – |
| CPV 24 | 1 | 0,58 | 0,58 | 0,58 | 0,58 | – |
| CPV 98 | 1 | 0,83 | 0,83 | 0,83 | 0,83 | – |
| CPV 72 | 1 | 1,00 | 1,00 | 1,00 | 1,00 | – |
| **celkem** | 42 | 0,41 | 0,67 | 0,88 | 0,91 | **0,88** |

## zkracene_lhuty

Hodnota: podíl řízení s lhůtou pod zákonným minimem. Výsledků nad minimálním základem (5): 9 (kandidátů 174).

| srovnávací skupina | n | p50 | p75 | p90 | p95 | navržený práh |
|---|---:|---:|---:|---:|---:|---:|
| lhuta_nabidky_nadlimitni_otevrene | 9 | 0,17 | 0,20 | 0,26 | 0,38 | – |
| **celkem** | 9 | 0,17 | 0,20 | 0,26 | 0,38 | **0,26** |

## opakovany_prijemce

Hodnota: počet dotací příjemce. Výsledků nad minimálním základem (2): 11404 (kandidátů 19194).

| srovnávací skupina | n | p50 | p75 | p90 | p95 | navržený práh |
|---|---:|---:|---:|---:|---:|---:|
| dotaceeu_2127: všichni příjemci | 11403 | 2,00 | 3,00 | 4,00 | 6,00 | 6,00 |
| red: všichni příjemci | 1 | 2,00 | 2,00 | 2,00 | 2,00 | – |
| **celkem** | 11404 | 2,00 | 3,00 | 4,00 | 6,00 | **6,00** |

## novy_subjekt

Hodnota: stáří dodavatele při první smlouvě (dny). Výsledků nad minimálním základem (1): 569 (kandidátů 569).

| srovnávací skupina | n | p50 | p75 | p90 | p95 | navržený práh |
|---|---:|---:|---:|---:|---:|---:|
| VVZ: dodavatelé se smlouvou | 569 | 9093,00 | 11584,00 | 12421,20 | 12645,20 | – |

### Poznámky k návrhu

* **novy_subjekt:** práh je součástí definice (365 dní, parametr `max_stari_dnu`) a ke schválení je spolu s ním;
  v datech VVZ je 0 z 569 dodavatelů do 365 dní od vzniku (p50 stáří 9 093 dní), percentil proto práh nenavrhuje.
* **zkracene_lhuty:** jen 9 zadavatelů nad minimem (5 otevřených řízení) a jen nadlimitní otevřené řízení; návrh
  p90 = 0,26 je velmi nejistý. Zákonná zkrácení (předběžné oznámení, § 57 odst. 2) indikátor nezohledňuje.
* **jedina_nabidka:** skupiny CPV mají nejvýš 12 výsledků – skupinové prahy se nenavrhují, jen celkový.
* **koncentrace_dodavatele:** rozložení se liší podle zdroje (VVZ 1 měsíc dat vs. seznam operací od 2023) –
  doporučení: prahy odděleně podle zdroje, skupinový práh jen u skupin s n ≥ 30 (seznam operací).
* **opakovany_prijemce:** 10 výsledků bez přiznané částky nemá stav k datu a pohled k publikaci je nevydá (D-039).
