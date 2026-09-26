"""Indikátory (blok 4). Výsledek je signál k prověření, nikdy zjištění (pravidlo 5).

Každý výsledek nese období, počet případů, základ, srovnávací skupinu a verzi metodiky
(`metodika/ind-<kod>-2026.09.json`); pod minimálním základem metodiky se nepočítá (výsledek nevznikne).
Počítá se v rámci jednoho zdroje (D-026). Texty jsou popisné, bez hodnotících výrazů (hlídá brána).

Spočítané na skutečných datech: koncentrace_dodavatele, jedina_nabidka, zkracene_lhuty,
opakovany_prijemce, novy_subjekt. Čekající na zdroj (jen funkce a testy na vzorových datech):
deleni_pod_limit (registr smluv), rizikove_pasmo (rizikové pásmo podle kotvy), zmena_struktury (obchodní rejstřík z kotvy).
Závislost na veřejných penězích se ve v1 nevydává (D-027).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg

from pvk.config import KOREN
from pvk.core import zajisti_metodiku
from pvk.zdroje import vvz as vvz_zdroj

POCITANE = ("koncentrace_dodavatele", "jedina_nabidka", "zkracene_lhuty", "opakovany_prijemce", "novy_subjekt")
CEKAJICI = ("deleni_pod_limit", "rizikove_pasmo", "zmena_struktury")
# platná verze metodiky indikátoru (starší verze mají stav „nahrazena“ a jejich výsledky se nepublikují)
VERZE = {"novy_subjekt": "2026.09.2", "zkracene_lhuty": "2026.09.2"}


def metodika(kod: str, verze: str | None = None) -> dict:
    verze = verze or VERZE.get(kod, "2026.09")
    return json.loads((KOREN / "metodika" / f"ind-{kod}-{verze}.json").read_text(encoding="utf-8"))


@dataclass
class Vysledek:
    indikator_kod: str
    ico: str | None
    obdobi_od: date
    obdobi_do: date
    pocet_pripadu: int
    zaklad: Decimal
    hodnota: Decimal
    srovnavaci_skupina: str
    text: str
    typ_castky: str | None = None
    stav_dat_k: date | None = None


def nad_minimem(vysledky: list[Vysledek], p: dict) -> list[Vysledek]:
    """Pod minimálním základem metodiky se nepočítá."""
    return [v for v in vysledky if v.pocet_pripadu >= int(p["min_pocet_pripadu"])]


def zapis(conn: psycopg.Connection, kod: str, vysledky: list[Vysledek]) -> int:
    definice = metodika(kod)
    md = Path(KOREN / "metodika" / "indikatory-2026.09.md")
    import hashlib

    metodika_id = zajisti_metodiku(conn, definice, hashlib.sha256(md.read_bytes()).hexdigest())
    vlozeno = 0
    for v in nad_minimem(vysledky, definice["parametry"]):
        subjekt = conn.execute("SELECT subjekt_id FROM core.subjekt_aktualni WHERE ico = %s AND valid_to = 'infinity'",
                               (v.ico,)).fetchone() if v.ico else None
        hodnoty = (v.indikator_kod, subjekt["subjekt_id"] if subjekt else None, v.obdobi_od, v.obdobi_do, v.pocet_pripadu,
                   v.zaklad, v.hodnota, v.typ_castky, metodika_id, v.text, v.srovnavaci_skupina, v.stav_dat_k)
        if conn.execute(
            "SELECT 1 FROM ind.indikator_vysledek WHERE indikator_kod = %s AND subjekt_id IS NOT DISTINCT FROM %s "
            "AND obdobi_od = %s AND obdobi_do = %s AND pocet_pripadu = %s AND zaklad = %s AND hodnota = %s "
            "AND typ_castky IS NOT DISTINCT FROM %s AND metodika_verze_id = %s AND text = %s AND srovnavaci_skupina = %s "
            "AND stav_dat_k IS NOT DISTINCT FROM %s", hodnoty).fetchone():
            continue  # stejný výsledek už je (opakovaný běh nic nezdvojí)
        conn.execute(
            "INSERT INTO ind.indikator_vysledek (indikator_kod, subjekt_id, obdobi_od, obdobi_do, pocet_pripadu, zaklad, "
            "hodnota, typ_castky, metodika_verze_id, text, srovnavaci_skupina, stav_dat_k) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", hodnoty)
        vlozeno += 1
    conn.commit()
    return vlozeno


def _pct(x: float) -> str:
    return f"{100 * x:.0f} %".replace(".", ",")


# --- 1. koncentrace dodavatele (klouzavě 36 měsíců, velikostní skupina) ------------------------------


def velikostni_skupina(objem: Decimal, pasma: list[list]) -> str:
    for nazev, do in pasma:
        if do is None or objem < Decimal(str(do)):
            return nazev
    return pasma[-1][0]


def koncentrace_dodavatele(conn: psycopg.Connection, p: dict) -> list[Vysledek]:
    """Podíl největšího dodavatele na objemu zadavatele (jeden zdroj, jeden typ částky, v CZK – cizí měna
    přepočtená kurzem ČNB) za posledních `okno_mesicu` měsíců dat zdroje; srovnávací skupina = velikost objemu."""
    vysledky = []
    for zdroj, zdroje, typ in p["zdroje"]:
        konec = conn.execute(
            "SELECT max(c.valid_from) AS d FROM core.castka c JOIN core.zdrojovy_zaznam_aktualni z "
            "ON z.zdrojovy_zaznam_id = c.zdrojovy_zaznam_id WHERE c.recorded_to = 'infinity' AND z.zdroj = ANY(%s) "
            "AND c.typ = %s AND c.valid_from <= current_date", (zdroje, typ)).fetchone()["d"]
        if konec is None:
            continue
        do = konec + timedelta(days=1)
        od = date(do.year - int(p["okno_mesicu"]) // 12, do.month, 1)
        radky = conn.execute(
            """SELECT sp.ico AS platce, sr.ico AS prijemce, sum(coalesce(c.hodnota_czk, c.hodnota)) AS objem, count(DISTINCT c.tok_id) AS toku
                 FROM core.castka c
                 JOIN core.tok_aktualni t ON t.tok_id = c.tok_id
                 JOIN core.subjekt_aktualni sp ON sp.subjekt_id = t.platce_subjekt_id AND sp.valid_to = 'infinity'
                 JOIN core.subjekt_aktualni sr ON sr.subjekt_id = t.prijemce_subjekt_id AND sr.valid_to = 'infinity'
                 JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = c.zdrojovy_zaznam_id
                WHERE c.recorded_to = 'infinity' AND z.zdroj = ANY(%s) AND c.typ = %s AND c.dph_rezim = 'bez_dph'
                  AND c.valid_from >= %s AND c.valid_from < %s AND (c.mena = 'CZK' OR c.hodnota_czk IS NOT NULL)
                GROUP BY 1, 2""", (zdroje, typ, od, do)).fetchall()
        # součet je v rámci jednoho typu, režimu DPH a měny (CZK); jiné kombinace se nesčítají (D-005)
        podle = defaultdict(dict)
        for r in radky:
            podle[r["platce"]][r["prijemce"]] = (Decimal(r["objem"]), r["toku"])
        for platce, dodavatele in podle.items():
            celkem = sum((o for o, _n in dodavatele.values()), Decimal(0))
            toku = sum(n for _o, n in dodavatele.values())
            if celkem <= 0:
                continue
            nejvetsi = max(o for o, _n in dodavatele.values())
            podil = nejvetsi / celkem
            skupina = f"{zdroj}: objem {velikostni_skupina(celkem, p['velikostni_skupiny'])}"
            vysledky.append(Vysledek(
                "koncentrace_dodavatele", platce, od, do, toku, celkem.quantize(Decimal("0.01")), podil.quantize(Decimal("0.0001")),
                skupina, f"Signál k prověření: největší dodavatel zadavatele má {_pct(float(podil))} objemu "
                f"({typ}, bez DPH) z {toku} zakázek v období {od:%m/%Y}–{konec:%m/%Y} ({zdroj}).", typ))
    return vysledky


# --- data formulářů VVZ (detail eForms + souhrn) ---------------------------------------------------


def formulare_vvz(conn: psycopg.Connection) -> list[dict]:
    souhrny = {r["id_ve_zdroji"]: r["obsah"] for r in conn.execute(
        "SELECT DISTINCT ON (id_ve_zdroji) id_ve_zdroji, obsah FROM raw.zaznam WHERE zdroj = 'vvz' "
        "ORDER BY id_ve_zdroji, cas_stazeni DESC, id DESC")}
    vysledek = []
    for r in conn.execute("SELECT DISTINCT ON (id_ve_zdroji) id_ve_zdroji, obsah FROM raw.zaznam WHERE zdroj = 'vvz_detail' "
                          "ORDER BY id_ve_zdroji, cas_stazeni DESC, id DESC"):
        s = souhrny.get(r["id_ve_zdroji"]) or {}
        data = s.get("data") or {}
        if data.get("formularZneplatnen") is True:
            continue  # zneplatněný formulář nahradil jiný
        u = vvz_zdroj.udaje_detailu(r["obsah"], s)
        if not u["eforms"]:
            continue
        deti = [d for d in vvz_zdroj.seznam(r["obsah"].get("deti")) if isinstance(d, dict) and isinstance(d.get("data"), dict)]
        root = next((d["data"]["ND-Root"] for d in deti if "ND-Root" in d["data"]), {})
        zahajeni = next((vvz_zdroj._datum(data.get(k)) for k in ("datumOdeslaniTed", "datumPrijetiVvz", "datumUverejneniVvz")
                         if data.get(k)), None)
        lhuty = sorted(d for x in u["lhuty"]["podani_nabidek"] if (d := vvz_zdroj._datum(x)))
        vysledek.append({
            "formular": r["id_ve_zdroji"], "zadavatel": (u["ico_zadavatelu"] or [None])[0], "cpv": (u["cpv"] or [""])[0],
            "nabidky": u["pocet_nabidek"], "druh_rizeni": u["druh_rizeni"], "typ": u["typ_oznameni"],
            "nadlimitni": bool(data.get("uverejnitTed")), "zahajeni": zahajeni, "lhuta": lhuty[0] if lhuty else None,
            "povaha": next(iter(vvz_zdroj._hodnoty(root, "BT-23-Procedure")), None),
            "predbezne_oznameni": bool(vvz_zdroj._hodnoty(root, "BT-125(i)-Lot")),
            "nalehavost": any(x is True or str(x).lower() == "true" for x in vvz_zdroj._hodnoty(root, "BT-106-Procedure")),
        })
    return vysledek


def _obdobi(formulare: list[dict]) -> tuple[date, date]:
    dny = [f["zahajeni"] for f in formulare if f["zahajeni"]]
    return min(dny), max(dny) + timedelta(days=1)


# --- 2. jediná nabídka (jen řízení se známým počtem nabídek, CPV skupina) ---------------------------


def jedina_nabidka(formulare: list[dict], p: dict) -> list[Vysledek]:
    """Podíl výsledků (částí) s jedinou nabídkou u zadavatele v CPV skupině (oddíl CPV, 2 číslice); jen
    výsledky se známým počtem nabídek (BT-759, BT-760 = tenders)."""
    if not formulare:
        return []
    od, do = _obdobi(formulare)
    skupiny: dict[tuple[str, str], list[int]] = defaultdict(list)
    for f in formulare:
        if f["zadavatel"] and f["typ"] == "result":
            skupiny[(f["zadavatel"], f["cpv"][:2] or "??")] += [int(n) for n in f["nabidky"]]
    vysledky = []
    for (zadavatel, cpv), pocty in skupiny.items():
        jedna = sum(1 for n in pocty if n == 1)
        vysledky.append(Vysledek(
            "jedina_nabidka", zadavatel, od, do, len(pocty), Decimal(len(pocty)), Decimal(jedna / len(pocty)).quantize(Decimal("0.0001")),
            f"CPV {cpv}", f"Signál k prověření: {jedna} z {len(pocty)} částí zakázek zadavatele v oddílu CPV {cpv} "
            f"mělo jedinou nabídku (VVZ, oznámení o výsledku)."))
    return vysledky


# --- 3. zkrácené lhůty (limit platný v den zahájení) ------------------------------------------------


def svatky(rok: int) -> set[date]:
    """Státní svátky a ostatní svátky ČR (zákon č. 245/2000 Sb.), včetně Velkého pátku a Velikonočního pondělí."""
    a, b, c = rok % 19, rok // 100, rok % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    mesic, den = divmod(h + ll - 7 * m + 114, 31)
    velikonoce = date(rok, mesic, den + 1)
    pevne = [(1, 1), (5, 1), (5, 8), (7, 5), (7, 6), (9, 28), (10, 28), (11, 17), (12, 24), (12, 25), (12, 26)]
    return {date(rok, m_, d_) for m_, d_ in pevne} | {velikonoce - timedelta(days=2), velikonoce + timedelta(days=1)}


def pracovni_dny(od: date, do: date) -> int:
    """Počet pracovních dnů po dni `od` až do dne `do` včetně."""
    s = svatky(od.year) | svatky(do.year)
    return sum(1 for n in range(1, (do - od).days + 1)
               if (x := od + timedelta(days=n)).weekday() < 5 and x not in s)


def limit_k_datu(conn: psycopg.Connection, kod: str, den: date) -> tuple[int, str] | None:
    r = conn.execute("SELECT hodnota, jednotka FROM core.limit WHERE kod = %s AND recorded_to = 'infinity' "
                     "AND valid_from <= %s AND %s < valid_to", (kod, den, den)).fetchone()
    return (int(r["hodnota"]), r["jednotka"]) if r else None


def minimalni_lhuta(conn: psycopg.Connection, f: dict, zkraceni: dict | None = None) -> tuple[str, int, str] | None:
    """Zákonné minimum lhůty pro podání nabídek platné v den zahájení (jen otevřené řízení; ostatní druhy
    mají lhůtu od výzvy, ne od oznámení, a z oznámení se nepočítají)."""
    if f["druh_rizeni"] != "open" or f["zahajeni"] is None:
        return None
    if f["nadlimitni"]:
        kod = "lhuta_nabidky_nadlimitni_otevrene"
    else:
        kod = ("lhuta_nabidky_podlimitni_otevrene_stavby" if f["povaha"] == "works"
               else "lhuta_nabidky_podlimitni_otevrene_dodavky_sluzby")
    lim = limit_k_datu(conn, kod, f["zahajeni"])
    if not lim:
        return None
    minimum, jednotka = lim
    # zákonná zkrácení (metodika ind-zkracene-lhuty-2026.09.2, ověřeno v e-Sbírce): podlimitní § 54 odst. 4,
    # nadlimitní dodávky a služby § 57 odst. 2 (předběžné oznámení nebo naléhavost)
    z = (zkraceni or {})
    if not f["nadlimitni"] and f.get("predbezne_oznameni") and "podlimitni_otevrene_predbezne_oznameni" in z:
        minimum -= int(z["podlimitni_otevrene_predbezne_oznameni"]["o_pracovnich_dnu"])
        kod += "+zkraceni_54_4"
    elif f["nadlimitni"] and f["povaha"] != "works" and (f.get("predbezne_oznameni") or f.get("nalehavost")):
        klic = ("nadlimitni_otevrene_dodavky_sluzby_predbezne_oznameni" if f.get("predbezne_oznameni")
                else "nadlimitni_otevrene_dodavky_sluzby_nalehavost")
        if klic in z:
            minimum = min(minimum, int(z[klic]["na_dnu"]))
            kod += "+zkraceni_57_2"
    return kod, minimum, jednotka


def zkracene_lhuty(conn: psycopg.Connection, formulare: list[dict], p: dict) -> list[Vysledek]:
    """Podíl otevřených řízení zadavatele, kde lhůta pro podání nabídek (BT-131) je kratší než zákonné minimum
    platné v den zahájení (bez zohlednění zákonných zkrácení – proto jen signál). Skupina = režim a povaha."""
    zahajene = [f for f in formulare if f["typ"] == "competition" and f["lhuta"] and f["zadavatel"]]
    if not zahajene:
        return []
    od, do = _obdobi(zahajene)
    skupiny: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for f in zahajene:
        m = minimalni_lhuta(conn, f, p.get("zkraceni"))
        if m is None:
            continue
        kod, minimum, jednotka = m
        kod = kod.split("+", 1)[0]  # srovnávací skupina = druh limitu (zkrácení se promítá jen do minima)
        delka = pracovni_dny(f["zahajeni"], f["lhuta"]) if jednotka == "pracovni_dny" else (f["lhuta"] - f["zahajeni"]).days
        skupiny[(f["zadavatel"], kod)].append(delka < minimum)
    vysledky = []
    for (zadavatel, kod), kratke in skupiny.items():
        k = sum(kratke)
        vysledky.append(Vysledek(
            "zkracene_lhuty", zadavatel, od, do, len(kratke), Decimal(len(kratke)), Decimal(k / len(kratke)).quantize(Decimal("0.0001")),
            kod, f"Signál k prověření: u {k} z {len(kratke)} otevřených řízení zadavatele byla lhůta pro nabídky kratší "
            f"než zákonné minimum platné v den zahájení ({kod}), i po zohlednění zákonných zkrácení (§ 54 odst. 4, "
            f"§ 57 odst. 2)."))
    return vysledky


# --- 4. opakovaný příjemce dotací -------------------------------------------------------------------


def opakovany_prijemce(conn: psycopg.Connection, p: dict) -> list[Vysledek]:
    """Počet dotací (toků) příjemce v jednom zdroji; stav k datu zdroje (D-039). Fyzické osoby se vynechávají."""
    vysledky = []
    for zdroj in p["zdroje"]:
        radky = conn.execute(
            """SELECT s.ico, count(DISTINCT t.tok_id) AS dotaci, min(t.valid_from) AS od, max(t.valid_from) AS do_,
                      sum(c.hodnota) FILTER (WHERE c.typ = 'dotace_priznana') AS priznano, min(c.stav_dat_k) AS stav
                 FROM core.tok_aktualni t
                 JOIN core.subjekt_aktualni s ON s.subjekt_id = t.prijemce_subjekt_id AND s.valid_to = 'infinity'
                 JOIN core.tok_zdroj_aktualni tz ON tz.tok_id = t.tok_id
                 JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = tz.zdrojovy_zaznam_id AND z.zdroj = %s
                 LEFT JOIN core.castka c ON c.tok_id = t.tok_id AND c.recorded_to = 'infinity' AND c.typ = 'dotace_priznana'
                                        AND c.mena = 'CZK'
                WHERE t.druh = 'dotace'
                GROUP BY s.ico""", (zdroj,)).fetchall()
        fo = {r["ico"] for r in conn.execute(
            "SELECT DISTINCT obsah->>'IČ příjemce' AS ico FROM raw.zaznam WHERE zdroj = 'dotaceeu_2127' "
            "AND lower(obsah->>'Právní forma příjemce') LIKE '%%fyzick%%'")} if zdroj == "dotaceeu_2127" else set()
        for r in radky:
            if r["ico"] in fo or r["dotaci"] < 1:
                continue
            stav = r["stav"]
            vysledky.append(Vysledek(
                "opakovany_prijemce", r["ico"], r["od"], r["do_"] + timedelta(days=1), r["dotaci"],
                Decimal(r["priznano"] or 0).quantize(Decimal("0.01")), Decimal(r["dotaci"]), f"{zdroj}: všichni příjemci",
                f"Signál k prověření: příjemce má v datech zdroje {zdroj} {r['dotaci']} dotací "
                f"({'stav k ' + stav.strftime('%d. %m. %Y') if stav else 'stav k datu neuveden'}).",
                "dotace_priznana", stav))
    return vysledky


# --- 5. nový subjekt (datum vzniku z kotvy; přeměny nejsou nový subjekt) ----------------------------


def novy_subjekt(conn: psycopg.Connection, p: dict, kotva) -> list[Vysledek]:
    """Stáří dodavatele (právnické osoby) v den toku: dny od vzniku podle kotvy k datu uzavření smlouvy k toku
    (událost uzavreni_smlouvy), jinak k začátku platnosti toku. Každý tok se hodnotí sám, bez historie prvního
    toku. Signálem je stáří do `max_stari_dnu` (práh podle D-052); u takového dodavatele se ověří přeměna –
    subjekt vzniklý přeměnou (fúze, rozdělení, změna právní formy podle ostatních skutečností v OR) nový není
    a spolu se subjektem bez dostupného záznamu OR se nehodnotí. Z kotvy se nic neukládá."""
    vysledky = []
    for zdroj, zdroje in p["zdroje"]:
        radky = conn.execute(
            """SELECT t.tok_id, s.ico, coalesce(min(u.datum), min(t.valid_from)) AS den
                 FROM core.tok_aktualni t
                 JOIN core.subjekt_aktualni s ON s.subjekt_id = t.prijemce_subjekt_id AND s.valid_to = 'infinity'
                 JOIN core.tok_zdroj_aktualni tz ON tz.tok_id = t.tok_id
                 JOIN core.zdrojovy_zaznam_aktualni z ON z.zdrojovy_zaznam_id = tz.zdrojovy_zaznam_id AND z.zdroj = ANY(%s)
                 LEFT JOIN core.udalost_aktualni u ON u.tok_id = t.tok_id AND u.typ = 'uzavreni_smlouvy'
                WHERE t.druh = 'verejna_zakazka' GROUP BY t.tok_id, s.ico""", (zdroje,)).fetchall()
        if not radky:
            continue
        subjekty = kotva.subjekty_podle_ico(sorted({r["ico"] for r in radky}))
        premena: dict[str, bool | None] = {}
        for r in radky:
            s = subjekty.get(r["ico"])
            if s is None or s.datum_vzniku is None or s.je_fyzicka_osoba is not False:
                continue  # fyzické osoby se nezobrazují (pravidlo 4); bez data vzniku se nehodnotí
            stari = (r["den"] - s.datum_vzniku).days
            if stari < 0:
                continue
            if stari <= int(p["max_stari_dnu"]):
                if r["ico"] not in premena:
                    premena[r["ico"]] = kotva.vznik_premenou(r["ico"])
                if premena[r["ico"]] is not False:
                    continue  # vznik přeměnou (nebo záznam OR nedostupný): nejde o nový subjekt
            vysledky.append(Vysledek(
                "novy_subjekt", r["ico"], r["den"], r["den"] + timedelta(days=1), 1, Decimal(1), Decimal(stari),
                f"{zdroj}: dodavatelé v den toku",
                f"Signál k prověření: dodavatel byl v den toku ({r['den']:%d. %m. %Y}, {zdroj}) {stari} dní od vzniku "
                f"(podle kotvy)" + (", přeměnou nevznikl." if stari <= int(p["max_stari_dnu"]) else ".")))
    return vysledky


# --- čekající na zdroj (testované na vzorových datech, na skutečných se nepočítají) ------------------


def deleni_pod_limit(smlouvy: list[dict], limit_czk: Decimal, okno_dni: int) -> list[dict]:
    """Registr smluv (čeká na zdroj): smlouvy téhož zadavatele s týmž dodavatelem v okně `okno_dni`, každá pod
    limitem VZMR, dohromady nad ním. smlouvy: {ico_zadavatele, ico_dodavatele, datum, hodnota_bez_dph}."""
    podle = defaultdict(list)
    for s in smlouvy:
        if s.get("hodnota_bez_dph") is not None and s["hodnota_bez_dph"] < limit_czk:
            podle[(s["ico_zadavatele"], s["ico_dodavatele"])].append(s)
    signaly = []
    for (zadavatel, dodavatel), rada in podle.items():
        rada.sort(key=lambda s: s["datum"])
        for i, prvni in enumerate(rada):
            okno = [s for s in rada[i:] if (s["datum"] - prvni["datum"]).days <= okno_dni]
            soucet = sum((s["hodnota_bez_dph"] for s in okno), Decimal(0))
            if len(okno) >= 2 and soucet >= limit_czk:
                signaly.append({"ico_zadavatele": zadavatel, "ico_dodavatele": dodavatel, "od": prvni["datum"],
                                "pocet_smluv": len(okno), "soucet_bez_dph": soucet})
                break
    return signaly


def rizikove_pasmo(zakazky: list[dict], pasma: dict[str, str], sledovana: set[str]) -> dict[str, dict]:
    """Kotva (čeká na zdroj): podíl objemu zadavatele u dodavatelů, které kotva řadí do rizikového pásma
    (pojem a hodnoty pásma přebírá z kotvy). zakazky: {ico_zadavatele, ico_dodavatele, hodnota};
    pasma: IČO -> rizikové pásmo podle kotvy; sledovana: pásma, která se počítají."""
    objem, ve_pasmu = defaultdict(Decimal), defaultdict(Decimal)
    pocet = defaultdict(int)
    for z in zakazky:
        objem[z["ico_zadavatele"]] += z["hodnota"]
        pocet[z["ico_zadavatele"]] += 1
        if pasma.get(z["ico_dodavatele"]) in sledovana:
            ve_pasmu[z["ico_zadavatele"]] += z["hodnota"]
    return {k: {"pocet_pripadu": pocet[k], "zaklad": objem[k], "podil": ve_pasmu[k] / objem[k]} for k in objem if objem[k]}


def zmena_struktury(zakazky: list[dict], zmeny: list[dict], okno_dni: int) -> list[dict]:
    """Obchodní rejstřík z kotvy (čeká na zdroj): změna statutárního orgánu, společníků nebo sídla dodavatele
    v okně ± `okno_dni` kolem uzavření smlouvy. Jen údaje OR na úrovni subjektu (pravidlo 2), bez vazeb na osoby.
    zakazky: {ico_dodavatele, datum}; zmeny: {ico, datum, druh}."""
    podle = defaultdict(list)
    for z in zmeny:
        podle[z["ico"]].append(z)
    signaly = []
    for zak in zakazky:
        blizke = [z for z in podle.get(zak["ico_dodavatele"], []) if abs((z["datum"] - zak["datum"]).days) <= okno_dni]
        if blizke:
            signaly.append({"ico_dodavatele": zak["ico_dodavatele"], "datum": zak["datum"],
                            "zmeny": sorted({z["druh"] for z in blizke})})
    return signaly


# --- běh nad skutečnými daty a rozložení pro návrh prahů --------------------------------------------


def spocitej(conn: psycopg.Connection, kotva) -> dict[str, dict]:
    """Spočítá pět indikátorů nad core/raw, zapíše výsledky nad minimem a vrátí přehled pro měření."""
    formulare = formulare_vvz(conn)
    vypocty = {
        "koncentrace_dodavatele": lambda p: koncentrace_dodavatele(conn, p),
        "jedina_nabidka": lambda p: jedina_nabidka(formulare, p),
        "zkracene_lhuty": lambda p: zkracene_lhuty(conn, formulare, p),
        "opakovany_prijemce": lambda p: opakovany_prijemce(conn, p),
        "novy_subjekt": lambda p: novy_subjekt(conn, p, kotva),
    }
    prehled = {}
    for kod, vypocet in vypocty.items():
        p = metodika(kod)["parametry"]
        vsechny = vypocet(p)
        nad = nad_minimem(vsechny, p)
        prehled[kod] = {"kandidatu": len(vsechny), "nad_minimem": len(nad), "vlozeno": zapis(conn, kod, vsechny),
                        "min_pocet_pripadu": p["min_pocet_pripadu"], "vysledky": nad}
    return prehled


def percentil(hodnoty: list[float], q: float) -> float:
    s = sorted(hodnoty)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q
    d, h = int(k), min(int(k) + 1, len(s) - 1)
    return s[d] + (s[h] - s[d]) * (k - d)


def rozlozeni(vysledky: list[Vysledek]) -> list[dict]:
    skupiny = defaultdict(list)
    for v in vysledky:
        skupiny[v.srovnavaci_skupina].append(float(v.hodnota))
    return [{"skupina": s, "n": len(h), **{f"p{int(q * 100)}": percentil(h, q) for q in (0.5, 0.75, 0.9, 0.95)}}
            for s, h in sorted(skupiny.items(), key=lambda x: -len(x[1]))]


def main() -> int:
    import logging

    from pvk.db import pripoj
    from pvk.kotva import vychozi_kotva

    logging.basicConfig(level=logging.INFO)
    with pripoj() as conn:
        prehled = spocitej(conn, vychozi_kotva())
    for kod, x in prehled.items():
        print(f"{kod}: kandidátů {x['kandidatu']}, nad minimem ({x['min_pocet_pripadu']}) {x['nad_minimem']}, vloženo {x['vlozeno']}")
        for r in rozlozeni(x["vysledky"])[:8]:
            print("   ", r)
    json.dump({k: {**{kk: vv for kk, vv in x.items() if kk != "vysledky"}, "rozlozeni": rozlozeni(x["vysledky"]),
                   "celkem": rozlozeni([Vysledek(v.indikator_kod, v.ico, v.obdobi_od, v.obdobi_do, v.pocet_pripadu,
                                                 v.zaklad, v.hodnota, "vše", v.text) for v in x["vysledky"]])}
               for k, x in prehled.items()},
              open(KOREN / "docs" / "blok4_indikatory.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
