"""Adaptéry zdrojů pro normalizaci: záznam raw -> NZaznam (tok, částky, události, IČO).

Typ, režim DPH a periodu částky určuje metodika (metodika/normalizace-2026.09.json, pole
`castky`), ne adaptér; adaptér jen říká, ze kterého pole zdroje částka pochází.
Tok vzniká vždy v rámci jednoho zdroje (D-026); propojení zdrojů (deduplikace) je samostatný krok.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import psycopg

from pvk.normalizace import NCastka, NTok, NUdalost, NZaznam, Statistika
from pvk.zdroje import vvz as vvz_zdroj

NEJMENSI_DATUM = date(1990, 1, 1)  # starší datum ve zdroji = chyba dat (např. rok 0202), ne událost


def _datum(hodnota) -> date | None:
    if not hodnota:
        return None
    try:
        d = date.fromisoformat(str(hodnota)[:10])
    except ValueError:
        return None
    return d if NEJMENSI_DATUM <= d <= date(2100, 1, 1) else None


def _cislo(hodnota) -> Decimal | None:
    if hodnota is None or hodnota == "":
        return None
    try:
        return Decimal(str(hodnota)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def posledni_zaznamy(conn: psycopg.Connection, zdroj: str, vcetne_vyvojovych: bool) -> list[dict]:
    """Nejnovější verze každého ID ve zdroji (změna ve zdroji = nový řádek raw)."""
    return conn.execute(
        """
        SELECT DISTINCT ON (id_ve_zdroji) id, id_ve_zdroji, url, obsah, beh_id
          FROM raw.zaznam WHERE zdroj = %s AND (%s OR NOT vyvojovy_vzorek)
         ORDER BY id_ve_zdroji, cas_stazeni DESC, id DESC
        """,
        (zdroj, vcetne_vyvojovych),
    ).fetchall()


def _castka(param: dict, pole: str, klic: str, hodnota, mena: str | None, datum: date,
            stav_dat_k: date | None = None) -> NCastka | str:
    """Částka podle metodiky (param['castky'][pole] = typ, dph_rezim, perioda); jinak důvod výjimky."""
    m = param["castky"].get(pole)
    if m is None:
        return "castka_bez_pravidla_metodiky"
    if not mena:
        return "castka_bez_meny"
    return NCastka(klic, m["typ"], hodnota, mena, m["dph_rezim"], m["perioda"], datum, stav_dat_k)


def _pridej_castku(z: NZaznam, stat: Statistika, tok: str, vysledek: NCastka | str, pole: str, hodnota) -> None:
    if isinstance(vysledek, str):
        z.vyjimky.append((vysledek, pole, str(hodnota)[:100], "částku nelze typovat podle metodiky"))
    else:
        z.castky.append((tok, vysledek))


# --- VVZ: souhrn formuláře a detail eForms ------------------------------------------------------

FORMULARE_ZMENY = {"38", "39", "40"}  # eForms: oznámení o změně smlouvy (dodatek)


def _root(detail: dict) -> dict | None:
    deti = [d for d in vvz_zdroj.seznam(detail.get("deti")) if isinstance(d, dict) and isinstance(d.get("data"), dict)]
    return next((d["data"]["ND-Root"] for d in deti if "ND-Root" in d["data"]), None)


def casti_formulare(root: dict) -> dict[str, dict]:
    """Části zakázky ve formuláři eForms (BT-137-Lot) -> předpokládaná hodnota části (BT-27-Lot), vítězné
    nabídky části (BT-720, IČO dodavatelů přes nabídku a skupinu dodavatelů) a uzavřené smlouvy (BT-145)."""
    orgs = vvz_zdroj._organizace(root)
    vysl = root.get("ND-RootExtension", {}).get("ND-NoticeResult", {})
    strany = {tp.get("OPT-210-Tenderer"): [orgs[t.get("OPT-300-Tenderer")].ico for t in vvz_zdroj.seznam(tp.get("ND-Tenderer"))
                                           if t.get("OPT-300-Tenderer") in orgs]
              for tp in vvz_zdroj.seznam(vysl.get("ND-TenderingParty"))}
    nabidky = {t.get("OPT-321-Tender"): t for t in vvz_zdroj.seznam(vysl.get("ND-LotTender"))}
    smlouvy = {s.get("OPT-316-Contract"): s for s in vvz_zdroj.seznam(vysl.get("ND-SettledContract"))}
    casti: dict[str, dict] = {}
    for lot in vvz_zdroj.seznam(root.get("ND-Lot")):
        if lot.get("BT-137-Lot"):
            casti[lot["BT-137-Lot"]] = {"odhad": vvz_zdroj._castky(vvz_zdroj._hodnoty(lot, "BT-27-Lot")), "ceny": [],
                                        "dodavatele": [], "smlouvy": []}
    for lr in vvz_zdroj.seznam(vysl.get("ND-LotResult")):
        cast = casti.get(lr.get("BT-13713-LotResult"))
        if cast is None or lr.get("BT-142-LotResult") != "selec-w":
            continue
        for ref in vvz_zdroj.seznam(lr.get("ND-LotResultTenderReference")):
            t = nabidky.get(ref.get("OPT-320-LotResult"))
            if t:
                cast["ceny"] += vvz_zdroj._castky([t.get("BT-720-Tender")])
                cast["dodavatele"] += [i for i in strany.get(t.get("OPT-310-Tender"), []) if i and i not in cast["dodavatele"]]
        for ref in vvz_zdroj.seznam(lr.get("ND-LotResultContractReference")):
            sm = smlouvy.get(ref.get("OPT-315-LotResult"))
            if sm and _datum(sm.get("BT-145-Contract")):
                cast["smlouvy"].append((sm.get("OPT-316-Contract") or ref.get("OPT-315-LotResult"),
                                        _datum(sm.get("BT-145-Contract"))))
    return casti


def casti_zakazek(conn, vcetne_vyvojovych: bool = True) -> dict[str, list[str]]:
    """Zakázky VVZ rozdělené na části podle detailů formulářů: evidenční číslo zakázky -> části (BT-137-Lot).
    Zakázka s jedinou částí (nebo bez detailu) je jeden tok; zakázka s více částmi je tok za každou část."""
    souhrny = {r["id_ve_zdroji"]: r["obsah"] for r in posledni_zaznamy(conn, "vvz", vcetne_vyvojovych)}
    vysledek: dict[str, set[str]] = {}
    for r in posledni_zaznamy(conn, "vvz_detail", vcetne_vyvojovych):
        zakazka = ((souhrny.get(r["id_ve_zdroji"]) or {}).get("data") or {}).get("evCisloZakazkyVvz")
        root = _root(r["obsah"])
        if zakazka and root is not None:
            vysledek.setdefault(zakazka, set()).update(casti_formulare(root))
    return {z: sorted(c) for z, c in vysledek.items() if len(c) > 1}


def _toky_zakazky(zakazka: str, casti: list[str], nazev: str | None) -> list[tuple[str, str | None]]:
    """(klíč toku, část): celá zakázka, nebo každá část zvlášť."""
    if not casti:
        return [(f"vvz:{zakazka}", None)]
    return [(f"vvz:{zakazka}:{c}", c) for c in casti]


def vvz(conn, param: dict, stat: Statistika, vcetne_vyvojovych: bool) -> list[NZaznam]:
    souhrny = {r["id_ve_zdroji"]: r for r in posledni_zaznamy(conn, "vvz", vcetne_vyvojovych)}
    casti = casti_zakazek(conn, vcetne_vyvojovych)
    vysledek = []
    for r in sorted(souhrny.values(), key=lambda r: (r["obsah"].get("data") or {}).get("datumUverejneniVvz") or ""):
        data = r["obsah"].get("data") or {}
        formular = r["id_ve_zdroji"]
        uverejneno = _datum(data.get("datumUverejneniVvz")) or _datum(r["obsah"].get("createdAt"))
        if uverejneno is None:
            continue
        zakazka = data.get("evCisloZakazkyVvz") or f"formular-{formular}"
        toky = _toky_zakazky(zakazka, casti.get(zakazka, []), data.get("nazevZakazky"))
        # událost celé zakázky rozdělené na části nepatří jedné části: tok_id zůstane prázdný, k tokům částí
        # vede přes zdrojový záznam (tok_zdroj)
        tok = toky[0][0] if len(toky) == 1 else None
        zadavatele = [z for z in (data.get("zadavatele") or []) if isinstance(z, dict)]
        z = NZaznam(r["id"], "vvz", formular, "zakazka", r["url"], uverejneno)
        z.ica = [(f"zadavatele[{i}].ico", zd.get("ico")) for i, zd in enumerate(zadavatele)]
        for klic, cast in toky:
            z.toky.append(NTok(klic, "verejna_zakazka", uverejneno,
                               platce=zadavatele[0].get("ico") if zadavatele else None,
                               predmet=(data.get("nazevZakazky") or "") + (f" – část {cast}" if cast else ""),
                               duvod_prijemce="dodavatel ze souhrnu formuláře neplyne"))
        druh = str(data.get("druhFormulare") or "")
        z.udalosti.append((tok, NUdalost(f"vvz:{formular}:zverejneni", "zverejneni", uverejneno,
                                         (data.get("uzivatelskyNazevFormulare") or f"formulář {druh}")[:200])))
        if druh in FORMULARE_ZMENY:
            z.udalosti.append((tok, NUdalost(f"vvz:{formular}:dodatek", "dodatek", uverejneno,
                                             "oznámení o změně smlouvy (formulář 38–40)")))
        if data.get("zakazkaZrusena") is True:
            z.udalosti.append((tok, NUdalost(f"vvz:{zakazka}:zruseni", "zruseni", uverejneno,
                                             "zadávací řízení zrušeno (příznak formuláře VVZ)")))
        if data.get("formularZneplatnen") is True:
            z.udalosti.append((tok, NUdalost(f"vvz:{formular}:zneplatneni", "zneplatneni",
                                             _datum(r["obsah"].get("updatedAt")) or uverejneno,
                                             "formulář zneplatněn (opraven jiným formulářem)")))
        vysledek.append(z)
    return vysledek


def vvz_detail(conn, param: dict, stat: Statistika, vcetne_vyvojovych: bool) -> list[NZaznam]:
    souhrny = {r["id_ve_zdroji"]: r["obsah"] for r in posledni_zaznamy(conn, "vvz", vcetne_vyvojovych)}
    casti_zak = casti_zakazek(conn, vcetne_vyvojovych)
    vysledek = []
    for r in posledni_zaznamy(conn, "vvz_detail", vcetne_vyvojovych):
        formular = r["id_ve_zdroji"]
        souhrn = souhrny.get(formular) or {}
        data = souhrn.get("data") or {}
        uverejneno = _datum(data.get("datumUverejneniVvz"))
        if uverejneno is None:
            continue
        u = vvz_zdroj.udaje_detailu(r["obsah"], souhrn)
        zakazka = data.get("evCisloZakazkyVvz") or f"formular-{formular}"
        z = NZaznam(r["id"], "vvz_detail", formular, "zakazka", r["url"], uverejneno)
        z.ica = [(f"zadavatel[{i}]", i_) for i, i_ in enumerate(u["ico_zadavatelu"])]
        z.ica += [(f"dodavatel[{i}]", i_) for i, i_ in enumerate(u["ico_dodavatelu"])]
        platce = u["ico_zadavatelu"][0] if u["ico_zadavatelu"] else None
        zmena = str(data.get("druhFormulare") or "") in FORMULARE_ZMENY
        pole = "vvz.zmena" if zmena else "vvz.BT-720"
        root = _root(r["obsah"])
        casti = casti_zak.get(zakazka, [])
        if casti and root is not None:
            # zakázka rozdělená na části: tok, dodavatel, částky a smlouvy za každou část
            ve_formulari = casti_formulare(root)
            for cast in [c for c in casti if c in ve_formulari] or casti:
                klic = f"vvz:{zakazka}:{cast}"
                c = ve_formulari.get(cast) or {"odhad": [], "ceny": [], "dodavatele": [], "smlouvy": []}
                z.toky.append(NTok(klic, "verejna_zakazka", uverejneno, platce=platce,
                                   prijemce=c["dodavatele"][0] if len(c["dodavatele"]) == 1 else None,
                                   prijemce_vice=len(c["dodavatele"]) > 1,
                                   predmet=(data.get("nazevZakazky") or "") + f" – část {cast}",
                                   duvod_prijemce=None if c["dodavatele"] else "dodavatel části ve formuláři neuveden"))
                for sid, datum in c["smlouvy"]:
                    z.udalosti.append((klic, NUdalost(f"vvz_detail:{formular}:smlouva:{sid}", "uzavreni_smlouvy",
                                                      datum, f"uzavření smlouvy na část {cast} (BT-145)")))
                uzavreni = min((d for _s, d in c["smlouvy"]), default=None)
                for i, (hodnota, mena) in enumerate(c["odhad"]):
                    _pridej_castku(z, stat, klic, _castka(param, "vvz.BT-27", f"vvz_detail:{formular}:{cast}:predpokladana:{i}",
                                                          hodnota, mena, uverejneno), "BT-27-Lot", hodnota)
                for i, (hodnota, mena) in enumerate(c["ceny"]):
                    _pridej_castku(z, stat, klic, _castka(param, pole, f"vvz_detail:{formular}:{cast}:{pole}:{i}", hodnota,
                                                          mena, uzavreni or uverejneno), pole, hodnota)
            vysledek.append(z)
            continue
        tok = f"vvz:{zakazka}"
        dodavatele = [i for i in u["ico_dodavatelu"] if i]
        z.toky.append(NTok(tok, "verejna_zakazka", uverejneno, platce=platce,
                           prijemce=dodavatele[0] if len(dodavatele) == 1 else None, prijemce_vice=len(dodavatele) > 1,
                           predmet=data.get("nazevZakazky"),
                           duvod_prijemce=None if dodavatele else "dodavatel ve formuláři neuveden (dosud nevybrán)"))
        deti = [d for d in vvz_zdroj.seznam(r["obsah"].get("deti")) if isinstance(d, dict)]
        oznameni = vvz_zdroj.parsuj_eforms({"id": r["obsah"].get("submission"), "variableId": formular, "data": data},
                                           deti)
        uzavreni = min((s.datum_uzavreni for s in (oznameni.smlouvy if oznameni else []) if s.datum_uzavreni),
                       default=None)
        for s in oznameni.smlouvy if oznameni else []:
            if s.datum_uzavreni:
                z.udalosti.append((tok, NUdalost(f"vvz_detail:{formular}:smlouva:{s.id}", "uzavreni_smlouvy",
                                                 s.datum_uzavreni, "uzavření smlouvy (BT-145)")))
        for i, (hodnota, mena) in enumerate(u["predpokladana_hodnota"]):
            _pridej_castku(z, stat, tok, _castka(param, "vvz.BT-27", f"vvz_detail:{formular}:predpokladana:{i}",
                                                  hodnota, mena, uverejneno), "BT-27", hodnota)
        for i, (hodnota, mena) in enumerate(u["vysoutezena_cena"]):
            _pridej_castku(z, stat, tok, _castka(param, pole, f"vvz_detail:{formular}:{pole}:{i}", hodnota, mena,
                                                  uzavreni or uverejneno), pole, hodnota)
        vysledek.append(z)
    return vysledek


# --- Seznam operací 2021–2027 ---------------------------------------------------------------------

EU_POLE_CASTEK = (  # pole souboru -> klíč pravidla metodiky
    ("Finanční prostředky v právních aktech příspěvek Unie CZK", "eu.pravni_akt"),
    ("Finanční prostředky v právních aktech národní veřejné zdroje CZK", "eu.pravni_akt"),
    ("Finanční prostředky vyúčtované v žádostech o platbu příspěvek Unie CZK", "eu.vyuctovano"),
    ("Finanční prostředky vyúčtované v žádostech o platbu národní veřejné zdroje CZK", "eu.vyuctovano"),
)


def _datum_souboru_eu(conn, beh_id: int | None) -> date | None:
    if beh_id is None:
        return None
    r = conn.execute("SELECT poznamka FROM raw.beh_prehled WHERE id = %s", (beh_id,)).fetchone()
    import re

    m = re.search(r'"datum_souboru":\s*"(\d{4}-\d{2}-\d{2})"', (r or {}).get("poznamka") or "")
    return date.fromisoformat(m.group(1)) if m else None


def dotaceeu_2127(conn, param: dict, stat: Statistika, vcetne_vyvojovych: bool) -> list[NZaznam]:
    vysledek = []
    stavy: dict[int, date | None] = {}
    for r in sorted(posledni_zaznamy(conn, "dotaceeu_2127", vcetne_vyvojovych), key=lambda r: r["id"]):
        o = r["obsah"]
        reg = o.get("Registrační číslo projektu")
        if not reg:
            continue
        if r["beh_id"] not in stavy:
            stavy[r["beh_id"]] = _datum_souboru_eu(conn, r["beh_id"])
        stav = stavy[r["beh_id"]]
        akt = _datum(o.get("Datum podepsání právního aktu"))
        start = akt or _datum(o.get("Skutečné datum zahájení fyzické realizace projektu")) or stav
        if start is None:
            continue
        tok = f"dotaceeu_2127:{reg}"
        z = NZaznam(r["id"], "dotaceeu_2127", r["id_ve_zdroji"], "operace_eu", r["url"], start)
        for pole in ("Datum podepsání právního aktu", "Datum zahájení zadávacího/výběrového řízení",
                     "Datum podpisu smlouvy/dodatku"):
            if o.get(pole) and _datum(o.get(pole)) is None:
                z.vyjimky.append(("datum_neplatne", pole, str(o.get(pole))[:40], "datum mimo rozsah 1990–2100"))
        z.ica = [("IČ příjemce", o.get("IČ příjemce"))]
        z.toky.append(NTok(tok, "dotace", start, prijemce=o.get("IČ příjemce"), predmet=o.get("Název projektu"),
                           duvod_platce="zdroj uvádí program, ne IČO poskytovatele (řídicího orgánu)"))
        if akt:
            z.udalosti.append((tok, NUdalost(f"{tok}:pravni_akt", "rozhodnuti_o_dotaci", akt,
                                             "podepsání právního aktu o poskytnutí podpory")))
        for pole, pravidlo in EU_POLE_CASTEK:
            hodnota = _cislo(o.get(pole))
            if hodnota is None:
                continue
            datum = akt if pravidlo == "eu.pravni_akt" and akt else (stav or start)
            _pridej_castku(z, stat, tok, _castka(param, pravidlo, f"{tok}:{pole}", hodnota, "CZK", datum, stav),
                           pole, hodnota)
        # veřejná zakázka v projektu: tok příjemce dotace -> dodavatel
        if o.get("Název veřejné zakázky") or o.get("IČ dodavatele veřejné zakázky"):
            zahajeni = _datum(o.get("Datum zahájení zadávacího/výběrového řízení"))
            podpis = _datum(o.get("Datum podpisu smlouvy/dodatku"))
            vz = f"dotaceeu_2127:{r['id_ve_zdroji']}"
            vz_start = zahajeni or podpis or start
            z.ica.append(("IČ dodavatele veřejné zakázky", o.get("IČ dodavatele veřejné zakázky")))
            z.toky.append(NTok(vz, "verejna_zakazka", vz_start, platce=o.get("IČ příjemce"),
                               prijemce=o.get("IČ dodavatele veřejné zakázky"), predmet=o.get("Název veřejné zakázky"),
                               duvod_prijemce="dodavatel bez IČ ve zdroji"))
            if zahajeni:
                z.udalosti.append((vz, NUdalost(f"{vz}:zahajeni", "zahajeni_rizeni", zahajeni)))
            if podpis:
                z.udalosti.append((vz, NUdalost(f"{vz}:podpis", "uzavreni_smlouvy", podpis,
                                                "podpis smlouvy/dodatku")))
            if "zruš" in str(o.get("Stav veřejné zakázky") or "").lower():
                z.udalosti.append((vz, NUdalost(f"{vz}:zruseni", "zruseni", stav or vz_start,
                                                "zakázka zrušena (stav ve zdroji)")))
            mena = o.get("Měna") or None
            for pole, pravidlo, datum in (
                ("Předpokládaná hodnota veřejné zakázky bez DPH", "eu.vz_predpokladana", zahajeni or vz_start),
                ("Cena veřejné zakázky podle smlouvy/dodatku bez DPH", "eu.vz_smluvni", podpis or vz_start),
            ):
                hodnota = _cislo(o.get(pole))
                if hodnota is not None:
                    _pridej_castku(z, stat, vz, _castka(param, pravidlo, f"{vz}:{pole}", hodnota, mena, datum),
                                   pole, hodnota)
        vysledek.append(z)
    return vysledek


# --- IS ReD -----------------------------------------------------------------------------------------


def red(conn, param: dict, stat: Statistika, vcetne_vyvojovych: bool) -> list[NZaznam]:
    """IS ReD: dotace založí tok (příjemce z tabulky příjemců), rozhodnutí se na tok naváže s rozhodnutou
    částkou (dotace_priznana, stav k datu exportu – D-039), záznam příjemce se naváže na toky svých dotací.
    Poskytovatel je v ReD jen položka číselníku bez IČO – plátce toku zůstává neurčený s důvodem."""
    zaznamy = posledni_zaznamy(conn, "red", vcetne_vyvojovych)
    prijemci = {r["id_ve_zdroji"]: r for r in zaznamy if "/prijemce/" in r["id_ve_zdroji"]}
    dotace = {r["id_ve_zdroji"]: r for r in zaznamy if "/dotace/" in r["id_ve_zdroji"]}
    vysledek, toky_prijemce = [], {}
    for r in dotace.values():
        o = r["obsah"]
        podpis = _datum(o.get("podpisDatum"))
        if podpis is None:
            continue
        tok = f"red:{o['iriDotace']}"
        prijemce = (prijemci.get(o.get("iriPrijemce")) or {}).get("obsah") or {}
        ico = prijemce.get("ico") or None
        z = NZaznam(r["id"], "red", r["id_ve_zdroji"], "dotace", r["url"], podpis)
        z.ica = [("prijemce.ico", ico)] if ico else []
        z.toky.append(NTok(tok, "dotace", podpis, prijemce=ico, predmet=o.get("nazev") or None,
                           duvod_platce="poskytovatel je v IS ReD položka číselníku bez IČO",
                           duvod_prijemce=None if prijemce else "příjemce není v raw (tabulka příjemců)"))
        z.udalosti.append((tok, NUdalost(f"{tok}:podpis", "rozhodnuti_o_dotaci", podpis,
                                         f"podpis; IS ReD, stav k {str(o.get('datumExportu'))[:10]}")))
        toky_prijemce.setdefault(o.get("iriPrijemce"), []).append((tok, podpis))
        vysledek.append(z)
    for r in zaznamy:
        o = r["obsah"]
        if "/rozhodnuti/" in r["id_ve_zdroji"] and o.get("iriDotace") in dotace:
            d = dotace[o["iriDotace"]]["obsah"]
            podpis = _datum(d.get("podpisDatum"))
            if podpis is None:
                continue
            tok = f"red:{o['iriDotace']}"
            stav = _datum(o.get("datumExportu"))
            z = NZaznam(r["id"], "red", r["id_ve_zdroji"], "dotace", r["url"], podpis)
            z.toky.append(NTok(tok, "dotace", podpis, duvod_platce="poskytovatel je v IS ReD položka číselníku bez IČO"))
            hodnota = _cislo(o.get("castkaRozhodnuta"))
            if hodnota is not None:
                _pridej_castku(z, stat, tok, _castka(param, "red.castkaRozhodnuta", f"{r['id_ve_zdroji']}:rozhodnuta",
                                                      hodnota, "CZK", podpis, stav), "castkaRozhodnuta", hodnota)
            vysledek.append(z)
        elif "/prijemce/" in r["id_ve_zdroji"] and toky_prijemce.get(r["id_ve_zdroji"]):
            toky = toky_prijemce[r["id_ve_zdroji"]]
            z = NZaznam(r["id"], "red", r["id_ve_zdroji"], "prijemce", r["url"], min(p for _t, p in toky))
            z.ica = [("ico", o.get("ico"))] if o.get("ico") else []
            z.toky += [NTok(t, "dotace", p, prijemce=o.get("ico") or None,
                            duvod_platce="poskytovatel je v IS ReD položka číselníku bez IČO") for t, p in toky]
            vysledek.append(z)
    return vysledek


ADAPTERY = {"vvz": vvz, "vvz_detail": vvz_detail, "dotaceeu_2127": dotaceeu_2127, "red": red}
