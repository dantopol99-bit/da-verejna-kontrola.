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
2. podíl záznamů bez částky v metadatech, u nichž text přílohy obsahuje cenu plnění: částku
   v cenovém kontextu (cena, hodnota, odměna, úhrada, nájemné, pojistné, celkem, …), která není
   jednotkovou sazbou (Kč/m², Kč za hodinu, hodinová sazba), sankcí (smluvní pokuta, úrok
   z prodlení), prahem („vyšší než“, „nad“, „minimálně“ před částkou), spoluúčastí či limitem
   pojištění, jistotou ani kaucí (rozhoduje věta před částkou a jednotka bezprostředně za ní);
3. podíl záznamů se znečitelněním (značky typu „XXXXX“, „█“, „anonymizováno“, černé obdélníky
   ve vektorovém PDF, černé bloky ve skenu).

Křížová kontrola metadata × text originálu (text: textová vrstva PDF, u stran bez textu OCR):

* **částka** – hodnota z metadat (bez DPH / s DPH) se hledá v textu v libovolném běžném zápisu
  (i bez označení měny v tabulkách), s tolerancí 1 Kč (zrcadlo zaokrouhluje), po přepočtu DPH
  (21/12/15/10 %), jako násobek periodické částky (12–60 měsíců; 60 = konvence RS „hodnota za 5 let“)
  nebo jako součet 2–3 cenových položek textu. Jinak „neshoda“ (uvádí-li text jinou cenu plnění),
  resp. „text bez ceny“; číslo navazující na písmeno („m3 EUR“) není částka;
* **IČO** – každé IČO z metadat se hledá v textu (i s mezerami mezi číslicemi, bez úvodních nul za
  štítkem „IČ“); u chybějícího se uvede, zda text obsahuje jiné platné IČO;
* **datum uzavření** – datem podpisu je jen „V ⟨Místo⟩ dne …“, „Datum podpisu: …“ a razítko
  elektronického podpisu (ne „usnesením … ze dne“). Rozpor = metadata uvádějí datum dřívější než
  poslední podpis v textu; je-li datum v metadatech pozdější než všechny podpisy v textu, nelze ověřit;
* **částka jen v příloze** – metadata bez částky, text uvádí částku v cenovém kontextu.

Znečitelnění: textové značky (XXXXX, █, *****; slovní značky „anonymizováno“, „znečitelněno“,
„osobní údaj“ jen jako zástupný údaj – v závorce, za dvojtečkou nebo samostatně na řádku, ne
doložka o uveřejnění typu „údaje, které by jinak podléhaly znečitelnění“), název souboru
(anonym, redig…), tmavý vyplněný obdélník ve vektorovém PDF velikosti řádku textu (výška 5–20 pt,
mimo záhlaví a zápatí, na řádku s textem, bez čitelného světlého textu uvnitř – to je záhlaví
tabulky), plně černý blok ve skenu (výplň ≥ 97 %, šířka ≤ 75 % strany).

Neshody jdou do `docs/pilot_vyjimky.csv` s návrhem verdiktu.

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

Z výběru P1 (čitelný text) se vyberou smlouvy s opakovaným nebo víceletým plněním:
* doba neurčitá ve větě o smlouvě/nájmu/objednávce (ne „souhlas se zveřejněním na dobu neurčitou“),
* doba plnění ≥ 366 dní, nebo ≥ 180 dní u průběžného plnění (služby, nájem, licence, servis) –
  doba se bere jen z věty o plnění, ne ze záruky, udržitelnosti projektu, archivace, mlčenlivosti,
* periodická částka (ročně / měsíčně / čtvrtletně; bez jednotkových cen typu Kč/m² a částek < 500 Kč),
* typicky opakované plnění (nájem, pacht, předplatné, paušál, pravidelný servis).

Verdikt „lze spolehlivě určit roční hodnotu“:
* **ano** – jednoznačná periodická částka (varianty bez DPH / s DPH / samotná DPH se slučují)
  přepočtená na rok; nebo doba plnění ≤ 1 rok s cenou za celé plnění; nebo celková cena výslovně
  za celou dobu trvání spolu s pevnou délkou trvání;
* **ne** – doba neurčitá bez periodické částky, jen jednotkové ceny, nebo text bez ceny;
* **nejasné** – více různých periodických částek, víceletá smlouva s cenou bez vazby na dobu trvání,
  opakované plnění bez údaje o periodě a délce.

## P4 – příjemci dotací, spárovatelnost na IČO přes ARES

Registry: IS ReD, seznam operací EU 2021–2027, SZIF. Rámce:
* IS ReD: příjemci s alespoň jednou dotací podepsanou v posledních 12 měsících dostupných dat
  (konec okna = nejnovější datum podpisu nejpozději k datu exportu; podpisy „po exportu“ jsou
  chyba dat a počítají se zvlášť);
* seznam operací 21+: všichni unikátní příjemci v posledním měsíčním souboru;
* SZIF: seznam příjemců za poslední fiskální rok (pokud je dostupný).

Fyzické osoby bez IČO jsou mimo rozsah platformy a z definice nespárovatelné: jejich podíl se
spočítá přesně na celém rámci (bez výběru) a jejich identifikační údaje se neukládají. Prostý náhodný
výběr 200 příjemců se losuje z příjemců v rozsahu (právnické osoby a podnikající fyzické osoby s IČO).
Spárovatelný = IČO existuje v ARES a název se shoduje (podobnost ≥ 0,80 po normalizaci právní formy,
diakritiky a interpunkce), nebo příjemce bez IČO (právnická osoba) má v ARES jednoznačnou shodu názvu.
U podnikajících fyzických osob se název neporovnává (ukládá se jen IČO); shoda = IČO existuje v ARES
a ARES je vede jako fyzickou osobu.

## Prahy doporučení (stanovené před měřením)

* (a) Systém může tvrdit **toky**, pokud P1 ≥ 90 %, P2 doloženě ≥ 50 % a P2 celkem ≥ 80 %;
  jinak jen **případy** (jednotlivé záznamy s odkazem na zdroj, bez agregovaných toků).
* (b) Indikátor závislosti na veřejných penězích **ano**, pokud P3 „ano“ ≥ 80 % a P4 ≥ 95 %
  ve všech registrech; jinak **ne** (v této verzi).
