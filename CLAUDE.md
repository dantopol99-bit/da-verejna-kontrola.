# Platforma veřejné kontroly – pravidla pro každou session

Druhý systém platformy **Datové pole** (česká datová analytika). Sleduje toky veřejných peněz
(smlouvy, veřejné zakázky, dotace). Kotvou je **Firemní databáze** – samostatný repozitář,
do kterého se **nezasahuje**. Tento systém kotvu nestaví znovu, napojuje se na ni výhradně přes IČO.

## Nepřekročitelná pravidla

1. **Jen veřejná, legálně dostupná data. Vysvětlitelnost před sofistikovaností.**
2. **Vlastnictví jen do úrovně obchodního rejstříku** (evidence skutečných majitelů je uzavřena
   od 17. 12. 2025 – nepoužívat, neobcházet).
3. **Centrální registr oznámení (majetková přiznání) se NEPOUŽÍVÁ vůbec.**
4. **Fyzické osoby se nikdy nezobrazují jako samostatné profily.**
5. **Indikátor = signál k prověření, nikdy zjištění.**
6. **Ve v1 žádné vazby osoba → politik.**

Odvozená pravidla (viz docs/decisions.md):

* Ochrany zdrojů (anti-bot výzvy, geoblokace, přihlášení) se neobcházejí. Nedostupný zdroj se
  zdokumentuje (docs/sources.md, raw.stazeni) a hledá se legální alternativa.
* Žádná lokální kopie registru subjektů: údaje z ARES / kotvy se neukládají (ani do raw, ani na disk).
* Identifikační údaje fyzických osob bez IČO se do raw neukládají (sloupec `redigovano`);
  hash záznamu se počítá z původního záznamu, takže původ zůstává ověřitelný.
* Výstupní texty nesmějí obsahovat hodnotící výrazy („podezřelý“, „rizikový dodavatel“,
  „propojen s“, „napojen na“ ve všech tvarech) – hlídá publikační brána.

## Architektura

| Vrstva | Schéma | Pravidlo |
|---|---|---|
| zdrojová data | `raw` | **pouze INSERT** (triggery, SQLSTATE `PV001`); každý záznam má zdroj, ID ve zdroji, soubor/URL, čas stažení, hash |
| model | `core` | **bitemporální**: `valid_from/valid_to` (date) + `recorded_from/recorded_to` (timestamptz, přiděluje DB). Nic se nepřepisuje, změna = nová verze přes `core.zapis_verzi()` (`PV002`) |
| výsledky | `ind` | pouze INSERT; ven jen přes `ind.*_k_publikaci` a publikační bránu |

Entity podle metodiky (core): `zdrojovy_zaznam`, `subjekt` (jen IČO), `tok`, `tok_zdroj`
(stav `dolozena`/`pravdepodobna`, metoda, skóre; skóre 1 je vyhrazeno doloženým vazbám),
`castka`, `udalost`, `limit` (rezervované slovo – vždy psát `core.limit`), `metodika_verze`;
v `ind`: `indikator_vysledek`, `souhrn`.

**Částka** má povinně typ (`predpokladana, vysoutezena, smluvni, zmena_dodatkem, dotace_priznana,
dotace_cerpana, vratka`), `dph_rezim`, `mena`, `perioda`. Sčítání napříč typy je technicky
znemožněno: v Pythonu `pvk.castka.Castka` / `secti()`, v SQL jen agregát `core.soucet()`
nad `core.typovana_castka` (chyba `PV003`); `sum()` ani `+` pro typovanou částku neexistují.

## Konvence

* Kód, komentáře, dokumentace a commity česky; identifikátory bez diakritiky.
* Stahování jen přes `pvk.http.Stahovac` (loguje každý pokus do `raw.stazeni`, obsahově adresované
  úložiště `data/raw/`, šetrné rozestupy dotazů, TLS vždy ověřované).
* Zápis do raw jen přes `pvk.raw`, do core jen přes `pvk.core.zapis_verzi()`.
* Kotva jen přes `pvk.kotva.subjekt_podle_ico()` (pilot: ARES; později `DbKotva`).
* Migrace: `db/migrace/NNNN_popis.sql`; aplikovaná migrace se nemění (runner hlídá SHA-256),
  změna struktury = nový soubor.
* Metodika: `metodika/<kod>.json` (parametry) + `.md` (popis); každý výsledek nese verzi metodiky.
  Prahy rozhodnutí se stanovují **před** měřením.
* Publikační podmínky jsou testy (`tests/test_publikacni_podminky.py`) a musí shodit build.
  Neoslabovat, nepřeskakovat, nemarkovat jako xfail.
* Každé netriviální rozhodnutí zapsat do `docs/decisions.md` (kontext, rozhodnutí, důsledky).
* Zdroje a jejich dostupnost: `docs/sources.md`.

## Příkazy

```
make setup      # .venv (Python 3.12) + závislosti
make db         # PostgreSQL (docker compose, port 55432; fallback lokální pg_ctl)
make migrate    # SQL migrace
make test       # všechny testy (vyžadují DB; DB testy běží v dočasné databázi pvk_test_*)
make lint       # ruff
make gate       # publikační brána nad výstupy
make pilot      # pilot: stažení vzorků do raw, P1–P4, docs/pilot_report.md + docs/pilot_vyjimky.csv
```

Systémové závislosti pilotu: `tesseract-ocr` + `tesseract-ocr-ces`, `poppler-utils` (OCR skenů).
