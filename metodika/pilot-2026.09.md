# Metodika pilot-2026.09

Verze metodiky pro pilot měření kvality dat. Parametry jsou v `pilot-2026.09.json` a zapisují se
do `core.metodika_verze`; každý výsledek pilotu nese kód této verze.

## Rámec výběrů

* Sledované období: záznamy zveřejněné od 2025-09-01 do 2026-08-31 (12 celých měsíců před pilotem).
* Náhodné výběry jsou deterministické: seed `PVK_PILOT_SEED` (výchozí 20260925) a odvozené seedy
  pro jednotlivá měření (P1, P2, P4 × registr).

## P1 – registr smluv, 200 smluv

Rámec: platné verze záznamů registru smluv zveřejněné ve sledovaném období.

* oficiální zdroj (data.smlouvy.gov.cz): denní dumpy náhodně vybraných dnů, z jejich platných
  záznamů prostý náhodný výběr;
* zrcadlo Hlídač státu (při nedostupnosti oficiálního zdroje): identifikátory verzí jsou rostoucí
  posloupnost, proto se nejdřív binárním hledáním najdou hranice ID odpovídající období a pak se
  losuje ID s odmítáním (neexistující ID a neplatné záznamy se zahodí). Výsledek je prostý náhodný
  výběr z platných verzí v období.

Měří se:
1. podíl záznamů, kde metadata obsahují IČO publikujícího subjektu, IČO alespoň jedné smluvní strany
   a částku (bez DPH, s DPH nebo v cizí měně);
2. podíl záznamů bez částky v metadatech, u nichž text přílohy obsahuje částku v cenovém kontextu
   (cena, hodnota, odměna, úhrada, nájemné, celkem, …);
3. podíl záznamů se znečitelněním (značky typu „XXXXX“, „█“, „anonymizováno“, černé obdélníky
   ve vektorovém PDF, černé bloky ve skenu).

Křížová kontrola metadata × text originálu: IČO stran, částka (s tolerancí 1 Kč a přepočtem DPH),
datum uzavření (poslední datum podpisu v textu). Neshody jdou do `docs/pilot_vyjimky.csv`
s návrhem verdiktu.

## P2 – 50 zakázek z VVZ, párování se smlouvami v registru smluv

Rámec: oznámení o výsledku zadávacího řízení (eForms 29–35) zveřejněná ve VVZ ve sledovaném
období, s vybraným dodavatelem. Prostý náhodný výběr pozic ve stabilním řazení (evidenční číslo
formuláře).

* **doložená vazba** (skóre 1): odkaz na smlouvu v registru smluv v poli eForms BT-151
  (URL smlouvy) nebo evidenční číslo zakázky ve VVZ nalezené v záznamu registru smluv
  se shodným IČO zadavatele;
* **pravděpodobná vazba** (skóre < 1): kandidáti z registru smluv se shodným IČO zadavatele
  i dodavatele; skóre = 0,4 (shoda IČO) + 0,3 × shoda data + 0,3 × shoda částky.
  Shoda data: 1 − |Δ dní| / 30 vůči datu uzavření smlouvy (BT-145); bez data uzavření
  okno −180 až +7 dní od zveřejnění oznámení se shodou 0,5. Shoda částky: 1 − relativní rozdíl / 0,10
  (porovnání bez DPH; u částky s DPH přepočet sazbou 21 % nebo 12 %). Práh pravděpodobné vazby 0,70.
  Skóre heuristiky je shora omezeno 0,999 – jistota je vyhrazena doloženým vazbám.

## P3 – roční hodnota u opakovaného / víceletého plnění

Z výběru P1 se vyberou smlouvy s opakovaným nebo víceletým plněním (doba neurčitá, doba určitá
delší než rok, periodické platby, nájem, servis, licence, …). Verdikt „lze spolehlivě určit roční
hodnotu“:
* **ano** – text uvádí částku za rok, nebo měsíční/čtvrtletní částku jednoznačně přepočitatelnou,
  nebo celkovou cenu výslovně za celou dobu trvání spolu s pevnou dobou trvání;
* **ne** – doba neurčitá bez periodické částky, jen jednotkové ceny bez objemu, nebo žádná částka;
* **nejasné** – protichůdné údaje, více různých periodických částek, nečitelný text.

## P4 – příjemci dotací, spárovatelnost na IČO přes ARES

Z každého registru (IS ReD, seznam operací EU 2021–2027, SZIF) prostý náhodný výběr 200 příjemců.
Spárovatelný = IČO existuje v ARES a název se shoduje (podobnost ≥ 0,80 po normalizaci právní formy),
nebo příjemce bez IČO (právnická osoba) má v ARES jednoznačnou shodu názvu. Fyzické osoby bez IČO
jsou nespárovatelné z definice a jejich identifikační údaje se neukládají.

## Prahy doporučení (stanovené před měřením)

* (a) Systém může tvrdit **toky**, pokud P1 ≥ 90 %, P2 doloženě ≥ 50 % a P2 celkem ≥ 80 %;
  jinak jen **případy** (jednotlivé záznamy s odkazem na zdroj, bez agregovaných toků).
* (b) Indikátor závislosti na veřejných penězích **ano**, pokud P3 „ano“ ≥ 80 % a P4 ≥ 95 %
  ve všech registrech; jinak **ne** (v této verzi).
