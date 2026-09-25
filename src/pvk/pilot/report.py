"""Report pilotu: docs/pilot_report.md, docs/pilot_vyjimky.csv a data po záznamech v docs/pilot_data/.

Report se skládá jen z uložených mezivýsledků (data/pilot/*.json), takže jde přegenerovat bez sítě.
Výsledky měření se zapisují i do ind.indikator_vysledek (období, počet případů, verze metodiky).
"""

from __future__ import annotations

import csv
import re
import statistics
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pvk.config import KOREN
from pvk.pilot.kontext import KOD_METODIKY, Kontext
from pvk.pilot.statistika import Podil, procenta

DOCS = KOREN / "docs"
DATA = DOCS / "pilot_data"


def _p(d: dict | None) -> Podil | None:
    return Podil(d["citatel"], d["jmenovatel"]) if d else None


def _t(d: dict | None) -> str:
    return _p(d).text() if d else "neměřeno"


def _datum(d: str | date | None) -> str:
    if not d:
        return "–"
    d = date.fromisoformat(str(d)[:10])
    return f"{d.day}. {d.month}. {d.year}"


def _cislo(x: float, mist: int = 3) -> str:
    """Desetinné číslo s českou desetinnou čárkou."""
    return f"{x:.{mist}f}".replace(".", ",")


def _popis_chyby(chyba: str | None) -> str:
    """Srozumitelný popis chyby spojení; plné znění je v raw.stazeni.chyba."""
    if not chyba:
        return ""
    if "Tunnel connection failed" in chyba:
        m = re.search(r"Tunnel connection failed: ([^')]+)", chyba)
        return f"síťová proxy prostředí pilotu cíl nedosáhla ({m.group(1) if m else 'tunnel'})"
    if "ProxyError" in chyba:
        return "síťová proxy prostředí pilotu spojení nenavázala"
    if "ConnectionResetError" in chyba or "Connection aborted" in chyba:
        return "spojení ukončeno protistranou bez odpovědi (connection reset)"
    if "Timeout" in chyba:
        return "vypršel časový limit spojení"
    if "SSLError" in chyba:
        return "chyba TLS"
    if "NameResolution" in chyba or "Name or service not known" in chyba:
        return "název serveru nelze přeložit (DNS)"
    return chyba.split(":")[0]


def _den_pred(d: str | date) -> date:
    return date.fromisoformat(str(d)[:10]) - timedelta(days=1)


def _zapis_csv(cesta: Path, radky: list[dict], sloupce: list[str]) -> None:
    cesta.parent.mkdir(parents=True, exist_ok=True)
    with cesta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sloupce, extrasaction="ignore")
        w.writeheader()
        for r in radky:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in sloupce})


# --- výjimky a data po záznamech --------------------------------------------------------------------


def zapis_vyjimky(p1: dict | None, p3: dict | None, docs: Path = DOCS) -> list[dict]:
    radky = []
    for mereni, zdroj in (("P1", p1), ("P3", p3)):
        for v in (zdroj or {}).get("vyjimky", []):
            radky.append({"mereni": mereni, **v})
    radky.sort(key=lambda r: (r["mereni"], r["udaj"], int(r["zaznam"])))
    for i, r in enumerate(radky, 1):
        r["id"] = f"V{i:03d}"
        r["potvrzeno"] = ""
    _zapis_csv(
        docs / "pilot_vyjimky.csv",
        radky,
        ["id", "mereni", "zaznam", "udaj", "hodnota_metadata", "nalezeno_v_textu", "odkaz_zaznamu",
         "odkaz_originalu", "navrh_verdiktu", "zduvodneni", "potvrzeno"],
    )
    return radky


def zapis_data(p1, p2, p3, p4, data: Path = DATA) -> None:
    if p1:
        radky = []
        for p in p1["polozky"]:
            k = p.get("kontroly") or {}
            radky.append({
                **p,
                "prilohy_pocet": len(p["prilohy"]),
                "prilohy_ocr": sum(1 for x in p["prilohy"] if (x.get("ocr_stran") or 0) > 0),
                "prilohy_hash_ok": sum(1 for x in p["prilohy"] if x.get("shoda_hashe")),
                "znecitelneni": "; ".join(p["znecitelneni"]),
                "kontrola_castky": k.get("castka"),
                "kontrola_data": k.get("datum_uzavreni"),
                "kontrola_ico": "; ".join(f"{i}:{v}" for i, v in (k.get("ico") or {}).items()),
            })
        _zapis_csv(data / "p1_vzorek.csv", radky, [
            "id_verze", "odkaz", "cas_zverejneni", "datum_uzavreni", "ico_subjektu", "ico_protistrany",
            "protistran_bez_ico", "castka_v_metadatech", "hodnota_bez_dph", "hodnota_vcetne_dph", "cizi_mena",
            "duvod_neuvedeni_ceny", "m1_ico_obe_strany_a_castka", "prilohy_pocet", "prilohy_hash_ok", "prilohy_ocr",
            "text_citelny", "castka_v_priloze", "m2_castka_jen_v_priloze", "m3_znecitelneno", "znecitelneni",
            "kontrola_castky", "kontrola_ico", "kontrola_data"])
    if p2:
        radky = []
        for x in p2["polozky"]:
            nejlepsi = [h["nejlepsi"] for h in x["heuristika"] if h["nejlepsi"]]
            top = max(nejlepsi, key=lambda k: k["skore"]) if nejlepsi else None
            radky.append({
                **x,
                "zadavatele_ico": " ".join(i for i in x["zadavatele_ico"] if i),
                "dolozene_vazby": "; ".join(f"{d['metoda']}:{d['id_verze']}{'' if d['zaznam_existuje'] else ' (neexistuje)'}"
                                            for d in x["dolozene"]),
                "heuristika_id_verze": top["id_verze"] if top else "",
                "heuristika_skore": top["skore"] if top else "",
                "heuristika_shoda_data": top["shoda_data"] if top else "",
                "heuristika_shoda_castky": top["shoda_castky"] if top else "",
                "kandidatu": sum(len(h["kandidati"]) for h in x["heuristika"]),
            })
        _zapis_csv(data / "p2_vzorek.csv", radky, [
            "ev_cislo_formulare", "ev_cislo_zakazky", "odkaz", "datum_uverejneni", "druh_formulare", "zdroj_podani",
            "zadavatele_ico", "pocet_smluv", "kategorie", "dolozene_vazby", "heuristika_id_verze", "heuristika_skore",
            "heuristika_shoda_data", "heuristika_shoda_castky", "kandidatu"])
    if p3:
        radky = [{**x, "periodicke": "; ".join(f"{k}: {', '.join(v)}" for k, v in x["periodicke"].items() if v)}
                 for x in p3["polozky"]]
        _zapis_csv(data / "p3_klasifikace.csv", radky, [
            "id_verze", "odkaz", "neurcita", "delka_dni", "periodicke", "verdikt", "rocni_hodnota", "duvod"])
    if p4:
        radky = []
        for registr, r in p4.items():
            for x in r.get("polozky", []):
                radky.append({"registr": registr, **x, "ma_ico": bool(x.get("ico")),
                              "ico": "" if x.get("je_fyzicka_osoba") else x.get("ico")})
        _zapis_csv(data / "p4_vzorek.csv", radky, [
            "registr", "id_ve_zdroji", "pravni_forma", "je_fyzicka_osoba", "ma_ico", "ico", "kategorie",
            "podobnost_nazvu"])


# --- ind: výsledky měření -------------------------------------------------------------------------


def zapis_ind(ctx: Kontext, mereni: list[tuple[str, dict | None, str]]) -> int:
    vlozeno = 0
    for kod, podil, text in mereni:
        if not podil or not podil["jmenovatel"]:
            continue
        existuje = ctx.conn.execute(
            "SELECT 1 FROM ind.indikator_vysledek WHERE indikator_kod = %s AND metodika_verze_id = %s "
            "AND obdobi_od = %s AND obdobi_do = %s AND pocet_pripadu = %s AND hodnota = %s",
            (kod, ctx.metodika_id, ctx.od, ctx.do, podil["jmenovatel"], round(podil["podil"], 6)),
        ).fetchone()
        if existuje:
            continue
        ctx.conn.execute(
            "INSERT INTO ind.indikator_vysledek (indikator_kod, obdobi_od, obdobi_do, pocet_pripadu, zaklad, hodnota, "
            "metodika_verze_id, text) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (kod, ctx.od, ctx.do, podil["jmenovatel"], podil["jmenovatel"], round(podil["podil"], 6), ctx.metodika_id, text),
        )
        vlozeno += 1
    ctx.conn.commit()
    return vlozeno


# --- doporučení ------------------------------------------------------------------------------------


def doporuceni(ctx: Kontext, p1, p2, p3, p4) -> dict:
    prahy = ctx.metodika["doporuceni"]

    def hodnota(d):
        return d["podil"] if d and d.get("jmenovatel") else None

    a_podminky = [
        ("P1 IČO obou stran i částka", hodnota(p1 and p1["m1_ico_obe_strany_a_castka"]), prahy["toky_min_p1_ico_obe_strany_a_castka"]),
        ("P2 spárováno doloženě", hodnota(p2 and p2["dolozene"]), prahy["toky_min_p2_dolozene"]),
        ("P2 spárováno celkem", hodnota(p2 and p2["sparovano_celkem"]), prahy["toky_min_p2_sparovano_celkem"]),
    ]
    b_podminky = [("P3 roční hodnota určitelná", hodnota(p3 and p3["ano"]), prahy["zavislost_min_p3_rocni_ano"])]
    for registr, r in (p4 or {}).items():
        b_podminky.append((f"P4 spárovatelnost – {REGISTRY_KRATCE.get(registr, registr)}",
                           hodnota(r.get("sparovatelne")) if r.get("stav") == "zmereno" else None,
                           prahy["zavislost_min_p4_sparovatelnost"]))

    def vyhodnot(podminky):
        splneno = all(v is not None and v >= prah for _, v, prah in podminky)
        chybi = [n for n, v, _ in podminky if v is None]
        return splneno, chybi

    a_ok, a_chybi = vyhodnot(a_podminky)
    b_ok, b_chybi = vyhodnot(b_podminky)
    return {"a": {"podminky": a_podminky, "splneno": a_ok, "chybi": a_chybi},
            "b": {"podminky": b_podminky, "splneno": b_ok, "chybi": b_chybi}}


def _tabulka_podminek(podminky) -> list[str]:
    radky = ["| Podmínka | Naměřeno | Práh | Splněno |", "|---|---|---|---|"]
    for nazev, v, prah in podminky:
        radky.append(f"| {nazev} | {procenta(v) if v is not None else 'neměřeno'} | ≥ {procenta(prah)} | "
                     f"{'ano' if v is not None and v >= prah else ('–' if v is None else 'ne')} |")
    return radky


# --- report -----------------------------------------------------------------------------------------


VERDIKTY_P3 = {"ano": "ano", "ne": "ne", "nejasne": "nejasné"}
VYRAZENI_P2 = {"zneplatneny_formular": "zneplatněný formulář", "bez_uzavrene_smlouvy": "bez uzavřené smlouvy",
               "neznama_struktura_formulare": "neznámá struktura formuláře",
               "stranka_bez_vysledku": "prázdná stránka výsledků"}
REGISTRY_KRATCE = {"red": "IS ReD", "dotaceeu_2127": "seznam operací 21+", "szif": "SZIF"}
DRUHY_VYJIMEK = {
    "castka": "částka z metadat v textu nenalezena, text uvádí jiné částky",
    "castka_chybi_v_metadatech": "částka jen v příloze (metadata ji neuvádějí)",
    "datum_uzavreni": "datum uzavření dřívější než poslední podpis v textu",
    "ico_strana": "IČO smluvní strany v textu nenalezeno",
    "ico_subjekt": "IČO publikujícího subjektu v textu nenalezeno",
    "rocni_hodnota (P3)": "roční hodnotu nelze spolehlivě určit",
}
VYSLEDKY_KONTROLY = {
    "shoda": "shoda",
    "shoda_po_prepoctu_dph": "shoda po přepočtu DPH",
    "shoda_nasobek_periody": "násobek periodické částky z textu",
    "shoda_souctu_polozek": "součet cenových položek z textu",
    "neshoda": "neshoda (výjimka k potvrzení)",
    "text_bez_ceny": "text bez ceny",
    "bez_castky_v_metadatech": "metadata bez částky",
    "cizi_mena": "cizí měna, v textu nenalezeno",
    "bez_textu": "bez čitelného textu",
    "nelze_overit": "nelze ověřit (poslední podpis bez data)",
    "bez_data_v_metadatech": "metadata bez data",
}
REGISTRY = {"red":"IS ReD (dotace ze státního rozpočtu a fondů)", "dotaceeu_2127": "Seznam operací EU 2021–2027",
            "szif": "SZIF (zemědělské dotace)"}
KATEGORIE_P4 = {
    "ico_ares_shoda_nazvu": "IČO v ARES, název odpovídá",
    "ico_ares_jiny_nazev": "IČO v ARES, název se liší",
    "ico_neexistuje_v_ares": "IČO v ARES neexistuje",
    "ico_neplatne": "IČO s neplatnou kontrolní číslicí",
    "nazev_ares_jednoznacne": "bez IČO, v ARES jednoznačně podle názvu",
    "nazev_ares_nejednoznacne": "bez IČO, v ARES více kandidátů",
    "bez_ico_nenalezeno": "bez IČO, v ARES nenalezeno",
    "fo_bez_ico": "fyzická osoba bez IČO (mimo rozsah)",
}


def vytvor(ctx: Kontext, trvani_s: float | None = None, docs: Path = DOCS) -> Path:
    dostupnost = ctx.nacti("dostupnost") or []
    p1, p2, p3, p4 = ctx.nacti("p1"), ctx.nacti("p2"), ctx.nacti("p3"), ctx.nacti("p4")
    vyjimky = zapis_vyjimky(p1, p3, docs)
    zapis_data(p1, p2, p3, p4, docs / "pilot_data")
    dop = doporuceni(ctx, p1, p2, p3, p4)
    mereni_ind = []
    if p1:
        mereni_ind += [("pilot_p1_ico_obe_strany_a_castka", p1["m1_ico_obe_strany_a_castka"], "Podíl záznamů RS s IČO obou stran i částkou."),
                       ("pilot_p1_castka_jen_v_priloze", p1["m2_castka_jen_v_priloze"], "Podíl záznamů RS s částkou jen v příloze."),
                       ("pilot_p1_znecitelneno", p1["m3_znecitelneno"], "Podíl záznamů RS se znečitelněním.")]
    if p2:
        mereni_ind += [("pilot_p2_dolozene", p2["dolozene"], "Podíl zakázek VVZ spárovaných se smlouvou v RS doloženě."),
                       ("pilot_p2_jen_heuristicky", p2["jen_heuristicky"], "Podíl zakázek VVZ spárovaných jen heuristicky.")]
    if p3:
        mereni_ind += [("pilot_p3_rocni_hodnota_ano", p3["ano"], "Podíl opakovaných/víceletých smluv s určitelnou roční hodnotou.")]
    for registr, r in (p4 or {}).items():
        if r.get("stav") == "zmereno":
            mereni_ind.append((f"pilot_p4_sparovatelne_{registr}", r["sparovatelne"], f"Podíl příjemců ({registr}) spárovatelných na IČO přes ARES."))
    zapis_ind(ctx, mereni_ind)

    r: list[str] = []
    w = r.append
    w("# Pilot: měření kvality dat pro Platformu veřejné kontroly")
    w("")
    w(f"Metodika `{KOD_METODIKY}` ([popis](../metodika/{KOD_METODIKY}.md), "
      f"[parametry](../metodika/{KOD_METODIKY}.json)) · sledované období {_datum(ctx.od)} – "
      f"{_datum(_den_pred(ctx.do))} · seed {ctx.seed} · "
      f"vygenerováno {datetime.now(UTC).astimezone().strftime('%d. %m. %Y %H:%M')} "
      + (f"příkazem `make pilot` (běh {trvani_s / 60:.0f} min)." if trvani_s
         else "příkazem `make pilot-report` z uložených mezivýsledků."))
    w("")
    w("Výsledky jsou měření kvality zdrojových dat, ne hodnocení subjektů. Všechny podíly jsou uvedeny "
      "s 95% intervalem spolehlivosti (Wilson).")
    w("")

    # --- shrnutí ---
    w("## Shrnutí – čtyři čísla")
    w("")
    w("| # | Měření | Výsledek |")
    w("|---|---|---|")
    if p1:
        w(f"| P1 | Registr smluv: IČO obou stran **i** částka v metadatech | **{_t(p1['m1_ico_obe_strany_a_castka'])}** |")
        w(f"| P1 | … částka jen v příloze (metadata bez částky, text ano) | {_t(p1['m2_castka_jen_v_priloze'])} |")
        w(f"| P1 | … znečitelněné přílohy | {_t(p1['m3_znecitelneno'])} |")
    else:
        w("| P1 | Registr smluv | neměřeno |")
    if p2:
        w(f"| P2 | Zakázky VVZ spárované se smlouvou v RS **doloženě** | **{_t(p2['dolozene'])}** |")
        w(f"| P2 | … **jen heuristicky** (IČO + částka + datum) | **{_t(p2['jen_heuristicky'])}** |")
        w(f"| P2 | … nespárováno | {_t(Podil(p2['pocty']['nesparovano'], p2['n']).jako_dict())} |")
    else:
        w("| P2 | Zakázky VVZ × registr smluv | neměřeno |")
    if p3:
        w(f"| P3 | Opakované/víceleté smlouvy: roční hodnota určitelná **ano** | **{_t(p3['ano'])}** |")
        w(f"| P3 | … **ne** | {_t(p3['ne'])} |")
        w(f"| P3 | … **nejasné** | {_t(p3['nejasne'])} |")
    else:
        w("| P3 | Roční hodnota | neměřeno |")
    for registr, x in (p4 or {}).items():
        if x.get("stav") == "zmereno":
            w(f"| P4 | Příjemci – {REGISTRY.get(registr, registr)}: spárovatelní na IČO přes ARES "
              f"(příjemci v rozsahu platformy) | **{_t(x['sparovatelne'])}** |")
            if x.get("podil_fo_bez_ico_v_ramci") and x["podil_fo_bez_ico_v_ramci"]["citatel"]:
                w(f"| P4 | … fyzické osoby bez IČO v celém rámci (mimo rozsah, nespárovatelné z definice) | "
                  f"{procenta(x['podil_fo_bez_ico_v_ramci']['podil'])} "
                  f"({x['podil_fo_bez_ico_v_ramci']['citatel']}/{x['podil_fo_bez_ico_v_ramci']['jmenovatel']}, úplný výčet) |")
        else:
            w(f"| P4 | Příjemci – {REGISTRY.get(registr, registr)} | nedostupné: {x.get('duvod') or x.get('chyba', '')} |")
    w("")
    w(f"**(a) Toky, nebo jen případy?** → **{'systém může tvrdit toky' if dop['a']['splneno'] else 'jen případy'}** "
      "(zdůvodnění v kapitole 5).")
    w(f"**(b) Indikátor závislosti na veřejných penězích?** → **{'ano' if dop['b']['splneno'] else 'ne (v této verzi)'}** "
      "(zdůvodnění v kapitole 5).")
    w("")

    # --- zdroje ---
    w("## 1. Zdroje a jejich dostupnost")
    w("")
    w("Endpointy jsou popsány v [docs/sources.md](sources.md). Test dostupnosti proběhl v rámci `make pilot` "
      "(nejvýš dva pokusy s odstupem 5 s; každý pokus je zapsán v `raw.stazeni`). Měření používají data stažená "
      "při prvním běhu pilotu (čas stažení je u každého souboru v `raw.stazeni`).")
    w("")
    w("| Zdroj | Endpoint | Stav | Detail |")
    w("|---|---|---|---|")
    for d in dostupnost:
        detail = f"HTTP {d['http_status']}" if d["http_status"] else _popis_chyby(d["chyba"])
        if (d.get("pokusu") or 1) > 1:
            detail = f"{d['pokusu']}. pokus: {detail}"
        stav = {"dostupne": "dostupné", "nedostupne": "**nedostupné**", "antibot_vyzva": "**anti-bot výzva**"}[d["stav"]]
        w(f"| {d['popis']} | `{d['url']}` | {stav} | {detail} |")
    w("")
    if p1 and p1["zdroj"] == "hlidac":
        w("**Registr smluv:** oficiální otevřená data (`data.smlouvy.gov.cz`) ani web `smlouvy.gov.cz` nebyly "
          "z prostředí pilotu dosažitelné (spojení ukončeno bez odpovědi serveru; podle monitoringu Hlídače státu, "
          "[statniweby/info/128](https://www.hlidacstatu.cz/statniweby/info/128), byl registr smluv v týdnu "
          "18.–25. 9. 2026 nedostupný 58,6 % času i z ČR). P1–P3 proto použily zrcadlo "
          "**Hlídač státu** (CC BY 3.0 CZ): metadata záznamů a kopie příloh. Každá kopie přílohy byla přijata jen "
          "tehdy, když se její SHA-256 shodoval s hashem přílohy z metadat registru smluv, tj. jde bajtově o tentýž "
          "soubor jako originál. Omezení zrcadla: částky jsou zobrazeny zaokrouhlené na celé koruny. "
          "Pipeline umí oficiální zdroj (denní dumpy XML) a přepne se na něj sama, jakmile bude dostupný "
          "(`PVK_RS_BACKEND=auto`).")
        w("")
    w("**NEN a ISVZ** (otevřená data VZ) nebyly dosažitelné; zakázky se čtou přímo z **Věstníku veřejných "
      "zakázek** (veřejné API webu VVZ), kam se oznámení z NEN i ostatních elektronických nástrojů odesílají. "
      "**SZIF** vrací místo dat JavaScriptovou anti-bot výzvu; ochranu neobcházíme, registr je v P4 veden "
      "jako nedostupný.")
    w("")

    # --- metoda ---
    w("## 2. Metoda")
    w("")
    w("* Náhodné výběry jsou deterministické (seed a odvozené seedy pro každé měření); opakované `make pilot` "
      "použije již stažená data z `raw.stazeni` a úložiště `data/raw/` (obsahově adresované podle SHA-256).")
    w("* Každý vybraný záznam je uložen do `raw.zaznam` se zdrojem, ID ve zdroji, URL, časem stažení a hashem; "
      "přílohy jako samostatné záznamy s hashem z metadat i hashem staženého souboru.")
    w(f"* Podrobná pravidla výběrů a verdiktů: [metodika/{KOD_METODIKY}.md](../metodika/{KOD_METODIKY}.md).")
    if p1:
        v = p1["vyber"]
        if v.get("metoda") == "skupiny_id_zrcadlo":
            w(f"* **P1 výběr:** {p1['n']} platných záznamů zveřejněných ve sledovaném období. ID verzí v RS se "
              f"přidělují po čtyřech (zbytek po dělení 4 se v čase mění), proto se losují skupiny čtyř po sobě "
              f"jdoucích ID v rozsahu {v['hranice_id'][0]}–{v['hranice_id'][1]} a v každé se hledá existující verze. "
              f"Losováno {v['skupin']} skupin ({v['dotazu']} dotazů): {v['prazdna_skupina']} prázdných, "
              f"{v['neplatna_verze']} neplatných verzí, {v['mimo_obdobi']} mimo období, {v['chyba_stazeni']} chyb "
              "stažení (vyřazeny). Výsledkem je prostý náhodný výběr z platných verzí v období.")
        else:
            w(f"* **P1 výběr:** {p1['n']} platných záznamů z denních dumpů náhodně vybraných dnů (oficiální zdroj).")
    if p2:
        m = p2["meta"]
        w(f"* **P2 výběr:** rámec {m['ramec']} oznámení o výsledku (eForms 29–35) zveřejněných ve VVZ ve sledovaném "
          f"období; losováno {m['losovano_pozic']} pozic, vyřazeno: "
          + (", ".join(f"{VYRAZENI_P2.get(k, k)} {v}" for k, v in m["odmitnuto"].items()) or "nic") + ".")
    for registr, x in (p4 or {}).items():
        if x.get("stav") == "zmereno":
            meta = x["meta"]
            if registr == "red":
                w(f"* **P4 IS ReD:** rámec {meta['ramec']} příjemců s dotací podepsanou v posledních 12 měsících "
                  f"dostupných dat ({_datum(meta['okno_od'])} – {_datum(_den_pred(meta['okno_do']))}; "
                  f"nejnovější podpis v datech {_datum(meta['posledni_podpis_v_datech'])}).")
            else:
                w(f"* **P4 {REGISTRY.get(registr, registr)}:** rámec {meta['ramec']} unikátních příjemců "
                  f"(soubor k {_datum(meta.get('datum_souboru'))}).")
    w("")

    # --- výsledky ---
    w("## 3. Výsledky")
    w("")
    if p1:
        rz = p1["rozpad"]
        w("### P1 – registr smluv")
        w("")
        w("| Ukazatel | Podíl |")
        w("|---|---|")
        w(f"| IČO publikujícího subjektu | {_t(rz['ico_subjektu'])} |")
        w(f"| IČO alespoň jedné smluvní strany | {_t(rz['ico_protistrany'])} |")
        w(f"| Částka v metadatech (bez DPH, s DPH nebo v cizí měně) | {_t(rz['castka_v_metadatech'])} |")
        w(f"| **IČO obou stran i částka** | **{_t(p1['m1_ico_obe_strany_a_castka'])}** |")
        w(f"| Metadata bez částky s uvedeným důvodem neuvedení ceny | {_t(rz['duvod_neuvedeni_ceny'])} |")
        w(f"| Čitelný text alespoň jedné přílohy | {_t(rz['text_citelny'])} |")
        w(f"| **Částka jen v příloze** (z celku) | **{_t(p1['m2_castka_jen_v_priloze'])}** |")
        w(f"| … ze záznamů bez částky v metadatech | {_t(rz['m2_mezi_bez_castky'])} |")
        w(f"| **Znečitelněné** (z celku) | **{_t(p1['m3_znecitelneno'])}** |")
        w(f"| … ze záznamů s čitelným textem | {_t(rz['m3_mezi_citelnymi'])} |")
        w("")
        duvody: dict[str, int] = {}
        for p in p1["polozky"]:
            for d in p["znecitelneni"]:
                duvody[d] = duvody.get(d, 0) + 1
        if duvody:
            w("Signály znečitelnění (záznam může mít více signálů): "
              + ", ".join(f"{k} {v}" for k, v in sorted(duvody.items(), key=lambda x: -x[1])) + ".")
            w("")
        kontroly: dict[str, dict[str, int]] = {"castka": {}, "datum_uzavreni": {}}
        for p in p1["polozky"]:
            for k in kontroly:
                hodnota = (p.get("kontroly") or {}).get(k) or "bez_textu"
                kontroly[k][hodnota] = kontroly[k].get(hodnota, 0) + 1
        w("Křížová kontrola metadata × text originálu (počty záznamů):")
        w("")
        for k, nazev in (("castka", "částka"), ("datum_uzavreni", "datum uzavření")):
            w(f"* {nazev}: " + ", ".join(f"{VYSLEDKY_KONTROLY.get(h, h)} {v}"
                                         for h, v in sorted(kontroly[k].items(), key=lambda x: -x[1])))
        w("")
        w("Data po záznamech: [docs/pilot_data/p1_vzorek.csv](pilot_data/p1_vzorek.csv).")
        w("")
    if p2:
        w("### P2 – zakázky z VVZ × smlouvy v registru smluv")
        w("")
        metody: dict[str, int] = {}
        for x in p2["polozky"]:
            for m in {d["metoda"] for d in x["dolozene"] if d["zaznam_existuje"]}:
                metody[m] = metody.get(m, 0) + 1
        skore = [h["nejlepsi"]["skore"] for x in p2["polozky"] if x["kategorie"] == "jen_heuristicky"
                 for h in x["heuristika"] if h["nejlepsi"] and h["nejlepsi"]["skore"] >= ctx.metodika["p2"]["prah_pravdepodobne"]]
        w("| Výsledek | Zakázek |")
        w("|---|---|")
        w(f"| Doloženě (odkaz BT-151 nebo evidenční číslo v RS) | {_t(p2['dolozene'])} |")
        w(f"| Jen heuristicky (skóre ≥ {_cislo(ctx.metodika['p2']['prah_pravdepodobne'], 2)}) | {_t(p2['jen_heuristicky'])} |")
        w(f"| Spárováno celkem | {_t(p2['sparovano_celkem'])} |")
        w(f"| Nespárováno | {_t(Podil(p2['pocty']['nesparovano'], p2['n']).jako_dict())} |")
        w("")
        det = p2.get("pocty_detail", {})
        if det:
            w("Rozpad: doloženě odkazem BT-151 na konkrétní smlouvu "
              f"{det.get('dolozene_odkaz_bt151', 0)}, doloženě jen evidenčním číslem zakázky "
              f"{det.get('dolozene_jen_ev_cislo', 0)}; heuristicky se shodou částky {det.get('heuristicky_s_castkou', 0)}, "
              f"heuristicky jen IČO + datum (skóre na prahu, částku nešlo porovnat nebo nesouhlasí) "
              f"{det.get('heuristicky_bez_castky', 0)}.")
            w("")
        if metody:
            w("Doložené vazby podle metody (zakázka může mít obě): "
              + ", ".join(f"`{k}` {v}" for k, v in metody.items()) + ".")
        ev = [d for x in p2["polozky"] for d in x["dolozene"] if d["metoda"] == "evidencni_cislo_vz"]
        if ev:
            vice = sum(1 for x in p2["polozky"] if any((d.get("zaznamu_s_ev_cislem") or 0) > 1
                                                          for d in x["dolozene"] if d["metoda"] == "evidencni_cislo_vz"))
            w(f"Evidenční číslo zakázky vede u {vice} z "
              f"{sum(1 for x in p2['polozky'] if any(d['metoda'] == 'evidencni_cislo_vz' for d in x['dolozene']))} "
              "zakázek na více záznamů RS (rámcové dohody, dynamické nákupní systémy, dílčí smlouvy): dokládá vazbu "
              "zakázka → skupina smluv, ne konkrétní smlouvu.")
        bt = [d for x in p2["polozky"] for d in x["dolozene"] if d["metoda"] == "odkaz_bt151"]
        if bt:
            rozdily = [d["rozdil_dni_uzavreni"] for d in bt if d.get("rozdil_dni_uzavreni") is not None]
            velke = [r for r in rozdily if abs(r) > ctx.metodika["p2"]["okno_dni_datum_uzavreni"]]
            w(f"Odkazů BT-151 do RS bylo {len(bt)}, všechny vedou na existující záznam, "
              f"{sum(1 for d in bt if d.get('platny') is False)} na záznam později zneplatněný; u {len(velke)} z "
              f"{len(rozdily)} se datum uzavření v RS a v oznámení liší o více než "
              f"{ctx.metodika['p2']['okno_dni_datum_uzavreni']} dní (až {max((abs(r) for r in velke), default=0)} dní).")
        if skore:
            w(f"Skóre heuristických vazeb (jen heuristicky spárované zakázky): min {_cislo(min(skore))}, "
              f"medián {_cislo(statistics.median(skore))}, max {_cislo(max(skore))}.")
        val = p2["validace_heuristiky"]
        if val["dolozenych_zakazek"]:
            duvody_txt = {
                "ev_cislo_vede_na_vice_zaznamu": "evidenční číslo vede na rámcovou/jinou smlouvu téže zakázky",
                "datum_uzavreni_rs_a_vvz_se_lisi": "datum uzavření v RS a ve VVZ se liší více než o okno",
                "dolozeny_zaznam_zneplatnen": "doložený záznam byl zneplatněn a zveřejněn znovu",
                "chybi_castka_nebo_ico_v_rs": "v RS chybí částka nebo IČO",
            }
            w(f"Kontrola heuristiky na doložených případech: u {val['dolozenych_zakazek']} doloženě spárovaných zakázek "
              f"našla heuristika doložený záznam nad prahem v {val['heuristika_nasla_dolozenou']} případech "
              f"(z toho jako nejlepšího kandidáta v {val['dolozena_je_nejlepsi']}). Důvody neshody: "
              + (", ".join(f"{duvody_txt.get(k, k)} {v}" for k, v in val.get("duvody_neshody", {}).items()) or "–")
              + ". Heuristika tedy není náhradou doložené vazby: v části případů najde jinou (často správnější, "
              "např. dílčí) smlouvu, v části případů doloženou smlouvu nenajde kvůli rozporu dat ve zdrojích.")
        w("")
        w("Skóre všech vazeb je zapsáno v `core.tok_zdroj` (stav, metoda, skóre, verze metodiky); data po "
          "zakázkách: [docs/pilot_data/p2_vzorek.csv](pilot_data/p2_vzorek.csv).")
        w("")
    if p3:
        w("### P3 – roční hodnota u opakovaného / víceletého plnění")
        w("")
        w(f"Z {p3['n_p1']} záznamů P1 mělo čitelný text a opakované nebo víceleté plnění **{p3['n_opakovane']}** "
          f"smluv (záznamy bez čitelného textu, které nešlo posoudit: {p3['bez_citelneho_textu']}).")
        w("")
        w("| Lze spolehlivě určit roční hodnotu? | Podíl |")
        w("|---|---|")
        w(f"| ano | {_t(p3['ano'])} |")
        w(f"| ne | {_t(p3['ne'])} |")
        w(f"| nejasné | {_t(p3['nejasne'])} |")
        w("")
        duvody = {}
        for x in p3["polozky"]:
            klic = f"{VERDIKTY_P3.get(x['verdikt'], x['verdikt'])}: {x['duvod']}"
            duvody[klic] = duvody.get(klic, 0) + 1
        for k, v in sorted(duvody.items(), key=lambda x: -x[1]):
            w(f"* {k} – {v}")
        w("")
        w("Klasifikace po smlouvách: [docs/pilot_data/p3_klasifikace.csv](pilot_data/p3_klasifikace.csv).")
        w("")
    if p4:
        w("### P4 – příjemci dotací: spárovatelnost na IČO přes ARES")
        w("")
        for registr, x in p4.items():
            if x.get("stav") != "zmereno":
                w(f"**{REGISTRY.get(registr, registr)}:** nedostupné – {x.get('duvod') or x.get('chyba')}.")
                w("")
                continue
            sl = x.get("slozeni_ramce") or {}
            celkem = sum(sl.values())
            w(f"**{REGISTRY.get(registr, registr)}** – rámec {celkem} příjemců: právnické osoby s IČO "
              f"{sl.get('po_s_ico', 0)}, bez IČO {sl.get('po_bez_ico', 0)}; fyzické osoby s IČO {sl.get('fo_s_ico', 0)}, "
              f"bez IČO {sl.get('fo_bez_ico', 0)} (mimo rozsah). Vzorek z {x.get('ramec_v_rozsahu')} příjemců v rozsahu "
              f"(n = {x['n']}): spárovatelné {_t(x['sparovatelne'])}; včetně IČO s odlišným názvem "
              f"{_t(x['sparovatelne_vcetne_jineho_nazvu'])}.")
            w("")
            for k, v in sorted(x["kategorie"].items(), key=lambda i: -i[1]):
                w(f"* {KATEGORIE_P4.get(k, k)}: {v}")
            w("")
        w("Data po příjemcích (bez identifikace fyzických osob): [docs/pilot_data/p4_vzorek.csv](pilot_data/p4_vzorek.csv).")
        w("")

    # --- výjimky ---
    w("## 4. Křížová kontrola a výjimky k potvrzení")
    w("")
    typy: dict[tuple[str, str], int] = {}
    verdikty: dict[str, int] = {}
    for v in vyjimky:
        typy[(v["mereni"], v["udaj"])] = typy.get((v["mereni"], v["udaj"]), 0) + 1
        druh = v["navrh_verdiktu"].split(" – ")[0]
        verdikty[druh] = verdikty.get(druh, 0) + 1
    w(f"[docs/pilot_vyjimky.csv](pilot_vyjimky.csv) obsahuje **{len(vyjimky)}** výjimek k potvrzení.")
    w("")
    if typy:
        w("| Měření | Výjimka | `udaj` v CSV | Počet |")
        w("|---|---|---|---|")
        for (mereni, udaj), pocet in sorted(typy.items()):
            w(f"| {mereni} | {DRUHY_VYJIMEK.get(udaj, udaj)} | `{udaj}` | {pocet} |")
        w("")
        w("Návrhy verdiktů: " + ", ".join(f"{k} {v}" for k, v in sorted(verdikty.items(), key=lambda x: -x[1])) + ".")
        w("")
    w("Každý řádek má údaj, hodnotu v metadatech, co bylo nalezeno v textu, odkaz na záznam a na originál "
      "přílohy a návrh verdiktu. Sloupec `potvrzeno` je prázdný pro vaše potvrzení (ANO / NE / poznámka). "
      "Citace z textu smluv se do CSV nepřebírají (mohou obsahovat osobní údaje); u částek je uvedeno klíčové "
      "slovo, podle kterého byl kontext označen jako cenový.")
    w("")

    # --- doporučení ---
    w("## 5. Doporučení")
    w("")
    w("Prahy byly stanoveny **před měřením** v parametrech metodiky (`doporuceni`).")
    w("")
    w("### (a) Systém může tvrdit toky, nebo jen případy?")
    w("")
    r += _tabulka_podminek(dop["a"]["podminky"])
    w("")
    if dop["a"]["splneno"]:
        w("**Doporučení: systém může tvrdit toky** (agregace plátce → příjemce), vždy s podílem objemu, který stojí "
          "na heuristickém párování.")
    else:
        w("**Doporučení: jen případy.** Platforma má ve v1 zobrazovat jednotlivé případy (zakázka, smlouva, dotace) "
          "s odkazem na zdroj a se stavem vazby (doložená / pravděpodobná se skóre), ne agregované toky mezi "
          "subjekty. Toky v `core` slouží jako vnitřní struktura; agregovat je lze jen tam, kde jsou vazby "
          "doložené a částky stejného typu, a každý souhrn musí nést podíl heuristické deduplikace.")
    if dop["a"]["chybi"]:
        w("")
        w("Neměřené podmínky: " + ", ".join(dop["a"]["chybi"]) + " – doporučení je podmíněné jejich doměřením.")
    w("")
    w("### (b) Indikátor závislosti na veřejných penězích")
    w("")
    r += _tabulka_podminek(dop["b"]["podminky"])
    w("")
    if dop["b"]["splneno"]:
        w("**Doporučení: ano** – s typovanými ročními částkami a podílem heuristiky v každém výsledku.")
    else:
        w("**Doporučení: ne (v této verzi).** Indikátor závislosti potřebuje roční hodnotu plnění a spolehlivé "
          "napojení příjemců na IČO; tam, kde podmínky splněny nejsou, by indikátor sčítal částky s nejasnou "
          "periodou nebo neúplný okruh příjemců. Doporučujeme vrátit se k němu po zavedení periody částky "
          "z textu smluv (P3) a po ověření výjimek.")
    if dop["b"]["chybi"]:
        w("")
        w("Neměřené podmínky: " + ", ".join(dop["b"]["chybi"]) + ".")
    w("")

    # --- omezení ---
    w("## 6. Omezení")
    w("")
    w("* Velikost vzorků (200 / 50 / 200 na registr) dává interval spolehlivosti zhruba ±7 p. b. (n = 200) "
      "a ±14 p. b. (n = 50); rozhodnutí blízko prahu je třeba číst s intervalem.")
    w("* Detekce částek, dat, znečitelnění a periodicity je pravidlová (regulární výrazy, OCR); verdikty jsou "
      "proto výjimkami k potvrzení, ne definitivním zjištěním.")
    w("* OCR se provádí jen u stran bez textové vrstvy a nejvýše u "
      f"{ctx.metodika['p1']['max_stran_ocr']} stran na přílohu.")
    w("* P2 hledá kandidáty ve zrcadle registru smluv (registr nemá vyhledávací API); v produkci bude párování "
      "probíhat nad plně načteným registrem v `raw`/`core`.")
    w("* IS ReD je publikován se zpožděním; rámec P4 pro ReD je proto posledních 12 měsíců dostupných dat.")
    w("")

    # --- reprodukce ---
    w("## 7. Reprodukce")
    w("")
    w("```")
    w("make pilot        # stáhne vzorky (nebo použije stažené), změří P1–P4, vytvoří tento report")
    w("make pilot-report # jen přegeneruje report z data/pilot/*.json")
    w("```")
    w("")
    w("Mezivýsledky: `data/pilot/*.json`; stažené soubory: `data/raw/<zdroj>/<sha256[:2]>/<sha256>.<přípona>`; původ: tabulky "
      "`raw.stazeni` a `raw.zaznam`; výsledky měření: `ind.indikator_vysledek` (kódy `pilot_*`); vazby "
      "zakázka–smlouva se skóre: `core.tok_zdroj`.")
    w("")

    cesta = docs / "pilot_report.md"
    cesta.write_text("\n".join(r) + "\n", encoding="utf-8")
    return cesta
