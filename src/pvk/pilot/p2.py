"""P2 – 50 zakázek z VVZ: párování se smlouvami v registru smluv (doloženě / heuristicky).

Doložená vazba (skóre 1):
  odkaz_bt151         oznámení uvádí u smlouvy URL záznamu v registru smluv (eForms BT-151)
  evidencni_cislo_vz  evidenční číslo zakázky (Z…) je uvedeno v záznamu RS se shodným IČO zadavatele
Pravděpodobná vazba (skóre < 1): kandidát z RS se shodným IČO zadavatele i dodavatele,
  skóre = w_ico + w_datum × shoda data + w_castka × shoda částky (parametry metodiky).
Registr smluv nemá vyhledávací API, proto se vyhledává ve zrcadle Hlídač státu (D-013).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from pvk import raw
from pvk.core import subjekt_pro_ico, zapis_entitu
from pvk.pilot.kontext import LOG, Kontext
from pvk.pilot.statistika import Podil
from pvk.zdroje.hlidac import ZDROJ as HS_ZDROJ
from pvk.zdroje.hlidac import HlidacRS
from pvk.zdroje.rs import ZaznamRS
from pvk.zdroje.vvz import VVZ, OznameniVVZ, SmlouvaVVZ, parsuj_eforms

# --- skórování (čisté funkce, testované) ----------------------------------------------------------


def ica_zaznamu(z: ZaznamRS) -> set[str]:
    ica = {s.ico for s in z.smluvni_strany if s.ico}
    if z.subjekt and z.subjekt.ico:
        ica.add(z.subjekt.ico)
    return ica


def shoda_data(sm: SmlouvaVVZ, z: ZaznamRS, datum_oznameni: date | None, p: dict) -> float:
    if z.datum_uzavreni is None:
        return 0.0
    if sm.datum_uzavreni is not None:
        okno = int(p["okno_dni_datum_uzavreni"])
        rozdil = abs((z.datum_uzavreni - sm.datum_uzavreni).days)
        return max(0.0, 1 - rozdil / okno)
    if datum_oznameni is not None:
        pred, po = p["okno_dni_bez_data_uzavreni"]
        if datum_oznameni + timedelta(days=pred) <= z.datum_uzavreni <= datum_oznameni + timedelta(days=po):
            return 0.5
    return 0.0


def shoda_castky(sm: SmlouvaVVZ, z: ZaznamRS, p: dict) -> tuple[float, str | None]:
    """Relativní shoda hodnoty vítězné nabídky (bez DPH) s částkou v RS; vrací (shoda, způsob porovnání)."""
    if sm.hodnota is None or sm.hodnota <= 0 or (sm.mena or "CZK") != "CZK":
        return 0.0, None
    tolerance = Decimal(str(p["tolerance_castky"]))
    varianty: list[tuple[Decimal, str]] = []
    if z.hodnota_bez_dph:
        varianty.append((z.hodnota_bez_dph, "bez_dph"))
    if z.hodnota_vcetne_dph:
        for sazba in p["sazby_dph"]:
            varianty.append((z.hodnota_vcetne_dph / (1 + Decimal(str(sazba))), f"s_dph/{1 + sazba:.2f}"))
    nejlepsi, zpusob = Decimal(0), None
    for hodnota, jak in varianty:
        rel = abs(hodnota - sm.hodnota) / sm.hodnota
        shoda = max(Decimal(0), 1 - rel / tolerance)
        if shoda > nejlepsi:
            nejlepsi, zpusob = shoda, jak
    return float(nejlepsi), zpusob


def skore(sm: SmlouvaVVZ, z: ZaznamRS, zadavatele: set[str], datum_oznameni: date | None, p: dict) -> dict:
    ica = ica_zaznamu(z)
    dodavatele = {d.ico for d in sm.dodavatele if d.ico}
    shoda_ico = bool(zadavatele & ica) and bool(dodavatele & ica)
    s_datum = shoda_data(sm, z, datum_oznameni, p)
    s_castka, zpusob = shoda_castky(sm, z, p)
    v = p["vahy"]
    celkem = (v["ico"] if shoda_ico else 0) + v["datum"] * s_datum + v["castka"] * s_castka
    return {
        "id_verze": z.id_verze,
        "shoda_ico": shoda_ico,
        "shoda_data": round(s_datum, 3),
        "shoda_castky": round(s_castka, 3),
        "porovnani_castky": zpusob,
        "skore": round(min(celkem, float(p["max_skore_heuristiky"])), 3) if shoda_ico else 0.0,
    }


# --- výběr ----------------------------------------------------------------------------------------


def vyber(ctx: Kontext, vvz: VVZ) -> tuple[list[tuple[dict, list, OznameniVVZ, int]], dict]:
    p = ctx.metodika["p2"]
    filtry = VVZ.filtry_vysledku(ctx.od, ctx.do, p["formulare_vysledku"])
    celkem = vvz.pocet(filtry)
    rng = ctx.rng("p2")
    pouzite: set[int] = set()
    vybrane = []
    odmitnute: dict[str, int] = {}
    while len(vybrane) < int(p["n"]) and len(pouzite) < celkem:
        pozice = rng.randrange(celkem)
        if pozice in pouzite:
            continue
        pouzite.add(pozice)
        _, polozky = vvz.hledej(filtry, pozice + 1, 1)
        if not polozky:
            odmitnute["stranka_bez_vysledku"] = odmitnute.get("stranka_bez_vysledku", 0) + 1
            continue
        souhrn = polozky[0]
        odp_deti, deti = vvz.deti(souhrn["id"])
        ozn = parsuj_eforms(souhrn, deti)
        duvod = None
        if ozn is None:
            duvod = "neznama_struktura_formulare"
        elif souhrn.get("data", {}).get("formularZneplatnen"):
            duvod = "zneplatneny_formular"
        elif not ozn.vybran_dodavatel or not any(s.dodavatele for s in ozn.smlouvy):
            duvod = "bez_uzavrene_smlouvy"
        if duvod:
            odmitnute[duvod] = odmitnute.get(duvod, 0) + 1
            continue
        rid = raw.zapis_zaznam(
            ctx.conn,
            zdroj="vvz",
            id_ve_zdroji=ozn.ev_cislo_formulare,
            url=odp_deti.url,
            cas_stazeni=odp_deti.cas_stazeni,
            obsah={"souhrn": souhrn, "formular": deti},
            format="json",
            stazeni_id=odp_deti.stazeni_id,
        )
        ctx.conn.commit()
        vybrane.append((souhrn, deti, ozn, rid))
        LOG.info("P2 výběr %d/%s: %s", len(vybrane), p["n"], ozn.ev_cislo_formulare)
    return vybrane, {"ramec": celkem, "losovano_pozic": len(pouzite), "odmitnuto": odmitnute, "filtry": filtry}


# --- párování -------------------------------------------------------------------------------------


class ParovacRS:
    def __init__(self, ctx: Kontext):
        self.ctx = ctx
        self.hs = HlidacRS(ctx.stahovac)
        self._detaily: dict[str, tuple[ZaznamRS | None, int | None]] = {}

    def detail(self, id_verze: str) -> tuple[ZaznamRS | None, int | None]:
        """Záznam RS a id jeho raw.zaznam (uloží se při prvním načtení)."""
        if id_verze in self._detaily:
            return self._detaily[id_verze]
        z, odp = self.hs.detail(id_verze)
        rid = None
        if z is not None:
            rid = raw.zapis_zaznam(
                self.ctx.conn,
                zdroj=HS_ZDROJ,
                id_ve_zdroji=z.id_verze,
                url=odp.url,
                cas_stazeni=odp.cas_stazeni,
                obsah=z.jako_dict(),
                format="html",
                stazeni_id=odp.stazeni_id,
            )
            self.ctx.conn.commit()
        self._detaily[id_verze] = (z, rid)
        return z, rid


def _rozdil_dni(sm: SmlouvaVVZ, z: ZaznamRS | None) -> int | None:
    """Rozdíl data uzavření v RS a v oznámení (BT-145) ve dnech; None, pokud některé chybí."""
    if z is None or z.datum_uzavreni is None or sm.datum_uzavreni is None:
        return None
    return (z.datum_uzavreni - sm.datum_uzavreni).days


def _okno_hledani(sm: SmlouvaVVZ, ozn: OznameniVVZ, p: dict) -> tuple[date, date] | None:
    if sm.datum_uzavreni:
        okno = int(p["okno_dni_datum_uzavreni"])
        return sm.datum_uzavreni - timedelta(days=okno), sm.datum_uzavreni + timedelta(days=okno)
    if ozn.datum_uverejneni:
        pred, po = p["okno_dni_bez_data_uzavreni"]
        return ozn.datum_uverejneni + timedelta(days=pred), ozn.datum_uverejneni + timedelta(days=po)
    return None


def paruj(ctx: Kontext, parovac: ParovacRS, ozn: OznameniVVZ) -> dict:
    p = ctx.metodika["p2"]
    zadavatele = {z.ico for z in ozn.zadavatele if z.ico}
    dolozene: list[dict] = []
    # (a) odkaz na RS v BT-151
    for sm in ozn.smlouvy:
        for idv in sm.id_verzi_rs:
            z, rid = parovac.detail(idv)
            dolozene.append(
                {
                    "smlouva": sm.id,
                    "id_verze": idv,
                    "metoda": "odkaz_bt151",
                    "zaznam_existuje": z is not None,
                    "platny": z.platny if z else None,
                    "id_smlouvy": z.id_smlouvy if z else None,
                    "shoda_ico_zadavatele": bool(z and zadavatele & ica_zaznamu(z)),
                    "rozdil_dni_uzavreni": _rozdil_dni(sm, z),
                    "raw_zaznam_id": rid,
                }
            )
    # (b) evidenční číslo zakázky v textu / metadatech RS
    if ozn.ev_cislo_zakazky:
        celkem_ev, radky = parovac.hs.hledej(f'"{ozn.ev_cislo_zakazky}"', max_stran=1)
        for r in radky[:10]:
            z, rid = parovac.detail(r.id_verze)
            if z is not None and zadavatele & ica_zaznamu(z):
                rozdily = [x for x in (_rozdil_dni(sm, z) for sm in ozn.smlouvy) if x is not None]
                dolozene.append(
                    {"smlouva": None, "id_verze": z.id_verze, "metoda": "evidencni_cislo_vz", "zaznam_existuje": True,
                     "platny": z.platny, "id_smlouvy": z.id_smlouvy, "shoda_ico_zadavatele": True,
                     "rozdil_dni_uzavreni": min(rozdily, key=abs) if rozdily else None,
                     "zaznamu_s_ev_cislem": celkem_ev, "raw_zaznam_id": rid}
                )
    # (c) heuristika pro každou smlouvu a dvojici IČO zadavatel × dodavatel
    heuristika = []
    for sm in ozn.smlouvy:
        kandidati: dict[str, dict] = {}
        okno = _okno_hledani(sm, ozn, p)
        for dod in sm.dodavatele:
            if not dod.ico or okno is None:
                continue
            for ico_z in sorted(zadavatele):
                dotaz = f"ico:{ico_z} AND ico:{dod.ico} AND podepsano:[{okno[0].isoformat()} TO {okno[1].isoformat()}]"
                _, radky = parovac.hs.hledej(dotaz, max_stran=2)
                for r in radky:
                    if r.id_verze in kandidati:
                        continue
                    z, rid = parovac.detail(r.id_verze)
                    if z is None:
                        continue
                    kandidati[r.id_verze] = {**skore(sm, z, zadavatele, ozn.datum_uverejneni, p),
                                             "id_smlouvy": z.id_smlouvy, "platny": z.platny, "raw_zaznam_id": rid}
        serazeni = sorted(kandidati.values(), key=lambda k: (-k["skore"], k["id_verze"]))
        heuristika.append(
            {
                "smlouva": sm.id,
                "datum_uzavreni": sm.datum_uzavreni,
                "hodnota_bez_dph": sm.hodnota,
                "mena": sm.mena,
                "dodavatele_ico": [d.ico for d in sm.dodavatele],
                "dodavatel_bez_ico": any(not d.ico for d in sm.dodavatele),
                "kandidati": serazeni,
                "nejlepsi": serazeni[0] if serazeni else None,
            }
        )
    prah = float(p["prah_pravdepodobne"])
    dolozeno = any(d["zaznam_existuje"] for d in dolozene)
    heuristicky = any(h["nejlepsi"] and h["nejlepsi"]["skore"] >= prah for h in heuristika)
    kategorie = "dolozene" if dolozeno else ("jen_heuristicky" if heuristicky else "nesparovano")
    # validace heuristiky proti doloženým vazbám: je doložený záznam heuristikou nalezen nad prahem?
    dolozena_id = {d["id_verze"] for d in dolozene if d["zaznam_existuje"]}
    validace = None
    if dolozena_id:
        nad_prahem = {k["id_verze"] for h in heuristika for k in h["kandidati"] if k["skore"] >= prah}
        nejlepsi = {h["nejlepsi"]["id_verze"] for h in heuristika if h["nejlepsi"] and h["nejlepsi"]["skore"] >= prah}
        validace = {
            "heuristika_nasla_dolozenou": bool(dolozena_id & nad_prahem),
            "dolozena_je_nejlepsi": bool(dolozena_id & nejlepsi),
            "heuristika_nasla_neco": bool(nad_prahem),
        }
    if validace is not None and not validace["heuristika_nasla_dolozenou"]:
        okno = int(p["okno_dni_datum_uzavreni"])
        duvody = set()
        for d in dolozene:
            if not d["zaznam_existuje"]:
                continue
            if d["platny"] is False:
                duvody.add("dolozeny_zaznam_zneplatnen")
            elif d["metoda"] == "evidencni_cislo_vz" and (d.get("zaznamu_s_ev_cislem") or 0) > 1:
                duvody.add("ev_cislo_vede_na_vice_zaznamu")
            elif d["rozdil_dni_uzavreni"] is not None and abs(d["rozdil_dni_uzavreni"]) > okno:
                duvody.add("datum_uzavreni_rs_a_vvz_se_lisi")
            else:
                duvody.add("chybi_castka_nebo_ico_v_rs")
        validace["duvody_neshody"] = sorted(duvody)
    kategorie_detail = kategorie
    if kategorie == "dolozene":
        kategorie_detail = "dolozene_odkaz_bt151" if any(
            d["metoda"] == "odkaz_bt151" and d["zaznam_existuje"] for d in dolozene) else "dolozene_jen_ev_cislo"
    elif kategorie == "jen_heuristicky":
        kategorie_detail = "heuristicky_s_castkou" if any(
            h["nejlepsi"] and h["nejlepsi"]["skore"] >= prah and h["nejlepsi"]["shoda_castky"] > 0 for h in heuristika
        ) else "heuristicky_bez_castky"
    return {"kategorie": kategorie, "kategorie_detail": kategorie_detail, "dolozene": dolozene,
            "heuristika": heuristika, "validace": validace}


# --- zápis do core (toky, částky, vazby se skóre) -------------------------------------------------


def zapis_do_core(ctx: Kontext, ozn: OznameniVVZ, raw_id: int, vysledek: dict, parovac: ParovacRS) -> None:
    conn = ctx.conn
    platnost = ozn.datum_uverejneni or ctx.od
    zz_vvz = zapis_entitu(conn, "zdrojovy_zaznam", f"vvz:{ozn.ev_cislo_formulare}", {
        "raw_zaznam_id": raw_id, "zdroj": "vvz", "id_ve_zdroji": ozn.ev_cislo_formulare, "druh": "zakazka",
        "url": ozn.odkaz}, platnost)
    if ozn.predpokladana_hodnota and ozn.predpokladana_mena:
        zapis_entitu(conn, "castka", f"vvz:{ozn.ev_cislo_formulare}:predpokladana", {
            "zdrojovy_zaznam_id": str(zz_vvz), "typ": "predpokladana", "hodnota": ozn.predpokladana_hodnota,
            "mena": ozn.predpokladana_mena, "dph_rezim": "bez_dph", "perioda": "celkem"}, platnost)
    zadavatel = next((z.ico for z in ozn.zadavatele if z.ico), None)
    platce = subjekt_pro_ico(conn, zadavatel) if zadavatel else None
    heur = {h["smlouva"]: h for h in vysledek["heuristika"]}
    prah = float(ctx.metodika["p2"]["prah_pravdepodobne"])
    for sm in ozn.smlouvy:
        dod = next((d.ico for d in sm.dodavatele if d.ico), None)
        prijemce = subjekt_pro_ico(conn, dod) if dod else None
        duvod = None if (platce and prijemce) else "subjekt bez českého IČO (zahraniční nebo neuvedeno)"
        od = sm.datum_uzavreni or platnost
        klic_toku = f"vvz:{ozn.ev_cislo_formulare}:{sm.id}"
        tok = zapis_entitu(conn, "tok", klic_toku, {
            "druh": "verejna_zakazka", "platce_subjekt_id": str(platce) if platce else None,
            "prijemce_subjekt_id": str(prijemce) if prijemce else None, "subjekt_neurcen_duvod": duvod,
            "predmet": (ozn.nazev or "")[:300] or None}, od)
        zapis_entitu(conn, "tok_zdroj", f"{klic_toku}:vvz", {
            "tok_id": str(tok), "zdrojovy_zaznam_id": str(zz_vvz), "stav": "dolozena", "metoda": "primy_zdroj",
            "skore": 1, "metodika_verze_id": ctx.metodika_id}, od)
        if sm.hodnota and sm.mena:
            zapis_entitu(conn, "castka", f"{klic_toku}:vysoutezena", {
                "tok_id": str(tok), "zdrojovy_zaznam_id": str(zz_vvz), "typ": "vysoutezena", "hodnota": sm.hodnota,
                "mena": sm.mena, "dph_rezim": "bez_dph", "perioda": "celkem"}, od)
        if sm.datum_uzavreni:
            zapis_entitu(conn, "udalost", f"{klic_toku}:uzavreni", {
                "tok_id": str(tok), "zdrojovy_zaznam_id": str(zz_vvz), "typ": "uzavreni_smlouvy",
                "datum": sm.datum_uzavreni}, od)
        # jedna vazba na záznam RS (odkaz BT-151 má přednost před evidenčním číslem a heuristikou);
        # stejná entita se v jedné transakci nesmí zapsat dvakrát (D-004)
        vazby: dict[str, tuple] = {}
        for d in sorted(vysledek["dolozene"], key=lambda d: d["metoda"] != "odkaz_bt151"):
            if d["zaznam_existuje"] and d["smlouva"] in (sm.id, None) and d["id_verze"] not in vazby:
                vazby[d["id_verze"]] = ("dolozena", d["metoda"], 1.0, d.get("raw_zaznam_id"))
        h = heur.get(sm.id)
        if h and h["nejlepsi"] and h["nejlepsi"]["skore"] >= prah and h["nejlepsi"]["id_verze"] not in vazby:
            vazby[h["nejlepsi"]["id_verze"]] = ("pravdepodobna", "heuristika_ico_datum_castka",
                                                h["nejlepsi"]["skore"], h["nejlepsi"].get("raw_zaznam_id"))
        for idv, (stav, metoda, sk, rid) in vazby.items():
            if rid is None:
                continue
            z, _ = parovac.detail(idv)
            zz_rs = zapis_entitu(conn, "zdrojovy_zaznam", f"{HS_ZDROJ}:{idv}", {
                "raw_zaznam_id": rid, "zdroj": HS_ZDROJ, "id_ve_zdroji": idv, "druh": "smlouva",
                "url": z.odkaz if z else f"https://smlouvy.gov.cz/smlouva/{idv}"},
                (z.cas_zverejneni.date() if z and z.cas_zverejneni else od))
            zapis_entitu(conn, "tok_zdroj", f"{klic_toku}:rs:{idv}", {
                "tok_id": str(tok), "zdrojovy_zaznam_id": str(zz_rs), "stav": stav, "metoda": metoda, "skore": sk,
                "metodika_verze_id": ctx.metodika_id,
                "zduvodneni": "odkaz nebo evidenční číslo v datech zdroje" if stav == "dolozena"
                else "shoda IČO zadavatele a dodavatele, data uzavření a částky v toleranci"}, od)
            if z is not None and (z.hodnota_bez_dph or z.hodnota_vcetne_dph):
                hodnota, rezim = ((z.hodnota_bez_dph, "bez_dph") if z.hodnota_bez_dph else (z.hodnota_vcetne_dph, "vcetne_dph"))
                zapis_entitu(conn, "castka", f"{klic_toku}:rs:{idv}:smluvni", {
                    "tok_id": str(tok), "zdrojovy_zaznam_id": str(zz_rs), "typ": "smluvni", "hodnota": hodnota,
                    "mena": "CZK", "dph_rezim": rezim, "perioda": "neurcena"}, od)
        conn.commit()


def mer(ctx: Kontext) -> dict:
    vvz = VVZ(ctx.stahovac)
    vybrane, meta = vyber(ctx, vvz)
    parovac = ParovacRS(ctx)
    polozky = []
    for i, (_souhrn, _deti, ozn, rid) in enumerate(vybrane, 1):
        LOG.info("P2 párování %d/%d: %s", i, len(vybrane), ozn.ev_cislo_formulare)
        vysledek = paruj(ctx, parovac, ozn)
        zapis_do_core(ctx, ozn, rid, vysledek, parovac)
        polozky.append({
            "ev_cislo_formulare": ozn.ev_cislo_formulare,
            "ev_cislo_zakazky": ozn.ev_cislo_zakazky,
            "odkaz": ozn.odkaz,
            "druh_formulare": ozn.druh_formulare,
            "datum_uverejneni": ozn.datum_uverejneni,
            "zdroj_podani": ozn.zdroj_podani,
            "zadavatele_ico": [z.ico for z in ozn.zadavatele],
            "pocet_smluv": len(ozn.smlouvy),
            "raw_zaznam_id": rid,
            **vysledek,
        })
    n = len(polozky)
    pocty = {k: sum(1 for x in polozky if x["kategorie"] == k) for k in ("dolozene", "jen_heuristicky", "nesparovano")}
    validace = [x["validace"] for x in polozky if x["validace"]]
    detail: dict[str, int] = {}
    for x in polozky:
        detail[x["kategorie_detail"]] = detail.get(x["kategorie_detail"], 0) + 1
    duvody_neshody: dict[str, int] = {}
    for v in validace:
        for d in v.get("duvody_neshody", []):
            duvody_neshody[d] = duvody_neshody.get(d, 0) + 1
    vysledky = {
        "meta": meta,
        "n": n,
        "pocty": pocty,
        "dolozene": Podil(pocty["dolozene"], n).jako_dict(),
        "jen_heuristicky": Podil(pocty["jen_heuristicky"], n).jako_dict(),
        "sparovano_celkem": Podil(pocty["dolozene"] + pocty["jen_heuristicky"], n).jako_dict(),
        "validace_heuristiky": {
            "dolozenych_zakazek": len(validace),
            "heuristika_nasla_dolozenou": sum(1 for v in validace if v["heuristika_nasla_dolozenou"]),
            "dolozena_je_nejlepsi": sum(1 for v in validace if v["dolozena_je_nejlepsi"]),
            "heuristika_nasla_neco": sum(1 for v in validace if v["heuristika_nasla_neco"]),
            "duvody_neshody": duvody_neshody,
        },
        "pocty_detail": detail,
        "polozky": polozky,
    }
    ctx.uloz("p2", vysledky)
    return vysledky
