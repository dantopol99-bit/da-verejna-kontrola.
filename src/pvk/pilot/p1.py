"""P1 – registr smluv, náhodný vzorek 200 smluv.

Měří se:
  m1  podíl záznamů s IČO obou stran i částkou v metadatech
  m2  podíl záznamů, kde je částka jen v příloze (metadata ji neuvádějí, text přílohy ano)
  m3  podíl záznamů se znečitelněním
a provede se křížová kontrola metadata × text originálu (výjimky k potvrzení).

Výběr: z oficiálních otevřených dat (denní dumpy), nebo – pokud nejsou dostupná – ze zrcadla
Hlídač státu: náhodné skupiny čtyř po sobě jdoucích ID verzí (ID se přidělují po čtyřech) s odmítáním
prázdných skupin, neplatných verzí a verzí zveřejněných mimo sledované období (viz metodika).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from PIL import Image

from pvk import raw
from pvk.http import Odpoved
from pvk.pilot.kontext import LOG, Kontext
from pvk.pilot.krizova import TextZaznamu, krizova_kontrola
from pvk.pilot.statistika import Podil
from pvk.text import analyza as a
from pvk.text.extrakce import (
    VERZE_DETEKCE,
    TextPrilohy,
    cerne_bloky,
    cerne_bloky_skenu_pdf,
    extrahuj,
    vektorove_cerne_obdelniky,
)
from pvk.zdroje.hlidac import HlidacRS
from pvk.zdroje.registr_smluv import NeshodaHashe, OficialniRS
from pvk.zdroje.rs import PrilohaRS, ZaznamRS

MAX_PRILOH = 12
MAX_VELIKOST_PRILOHY = 60 * 1024 * 1024


# --- výběr ---------------------------------------------------------------------------------------


def zvol_zdroj(ctx: Kontext) -> tuple[str, dict]:
    volba = ctx.nast.pilot_rs_backend  # zrcadlo jen v pilotu (D-030)
    info: dict = {"volba": volba}
    if volba == "hlidac":
        return "hlidac", info
    oficialni = OficialniRS(ctx.stahovac)
    dostupny = oficialni.dostupny()
    posledni = ctx.conn.execute(
        "SELECT cas_stazeni, http_status, chyba FROM raw.stazeni WHERE zdroj = 'registr_smluv' "
        "ORDER BY cas_stazeni DESC LIMIT 1"
    ).fetchone()
    info["test_dostupnosti"] = dict(posledni) if posledni else None
    if dostupny:
        return "oficialni", info
    if volba == "oficialni":
        raise RuntimeError("oficiální otevřená data registru smluv nejsou dostupná a PVK_PILOT_RS_BACKEND=oficialni")
    return "hlidac", info


def _ids_dne(hs: HlidacRS, den) -> list[int]:
    _, radky = hs.hledej(f"zverejneno:[{den.isoformat()} TO {den.isoformat()}]", max_stran=1)
    return sorted(int(r.id_verze) for r in radky)


def vzorek_hlidac(ctx: Kontext, hs: HlidacRS, n: int) -> tuple[list[tuple[ZaznamRS, Odpoved]], dict]:
    # hranice ID a známé zbytky modulo 4 z vyhledávání po dnech (začátek, konec, každý měsíc)
    znama: dict[int, int] = {}
    dny = [ctx.od + timedelta(days=30 * i) for i in range(0, 13)] + [ctx.do - timedelta(days=1)]
    ids_dnu: dict[str, list[int]] = {}
    for den in dny:
        if den >= ctx.do:
            den = ctx.do - timedelta(days=1)
        ids = _ids_dne(hs, den)
        ids_dnu[den.isoformat()] = ids
        znama.update({i: i % 4 for i in ids})
    zacatek, konec = ids_dnu[ctx.od.isoformat()], ids_dnu[(ctx.do - timedelta(days=1)).isoformat()]
    if not zacatek or not konec:
        raise RuntimeError("P1: nelze určit hranice ID verzí pro sledované období")
    lo, hi = min(zacatek) - 20000, max(konec) + 20000
    rng = ctx.rng("p1")
    skupiny: set[int] = set()
    prijate: list[tuple[ZaznamRS, Odpoved]] = []
    stat = {"hranice_id": [lo, hi], "skupin": 0, "dotazu": 0, "prazdna_skupina": 0, "neplatna_verze": 0,
            "mimo_obdobi": 0, "chyba_stazeni": 0}
    while len(prijate) < n:
        g = rng.randrange(lo // 4, hi // 4 + 1)
        if g in skupiny:
            continue
        skupiny.add(g)
        stat["skupin"] += 1
        nejblizsi = min(znama, key=lambda i: abs(i - 4 * g))
        poradi = [znama[nejblizsi]] + [r for r in range(4) if r != znama[nejblizsi]]
        nalez, chyba = None, False
        for r in poradi:
            idv = 4 * g + r
            z, odp = hs.detail(idv)
            stat["dotazu"] += 1
            if z is not None:
                nalez = (z, odp)
                znama[idv] = r
                break
            if odp.status not in (404, 410):
                chyba = True
        if nalez is None:
            stat["chyba_stazeni" if chyba else "prazdna_skupina"] += 1
            continue
        z, odp = nalez
        if not z.platny:
            stat["neplatna_verze"] += 1
            continue
        if z.cas_zverejneni is None or not (ctx.od <= z.cas_zverejneni.date() < ctx.do):
            stat["mimo_obdobi"] += 1
            continue
        prijate.append((z, odp))
        if len(prijate) % 20 == 0:
            LOG.info("P1 výběr: %d/%d (skupin %d, dotazů %d)", len(prijate), n, stat["skupin"], stat["dotazu"])
    return prijate, stat


# --- zpracování záznamu -------------------------------------------------------------------------


def text_prilohy(ctx: Kontext, odp: Odpoved, nazev: str) -> TextPrilohy:
    """Text přílohy s cache podle SHA-256 souboru (OCR je drahé)."""
    cache = ctx.nast.data_dir / "cache" / "text" / f"{odp.sha256}.json"
    if cache.is_file():
        data = json.loads(cache.read_text(encoding="utf-8"))
        tp = TextPrilohy(**{**data, "verze_detekce": data.get("verze_detekce", 1)})
        if tp.verze_detekce == VERZE_DETEKCE:
            return tp
        # pravidla detekce se změnila: text (a OCR) zůstává, přepočítá se jen detekce ve vektorovém PDF
        if tp.format == "pdf":
            tp.cerne_obdelniky = vektorove_cerne_obdelniky(Path(odp.cesta))
            if tp.ocr_stran:
                tp.cerne_bloky_sken = cerne_bloky_skenu_pdf(Path(odp.cesta), int(ctx.metodika["p1"]["max_stran_ocr"]))
        elif tp.format == "obrazek":
            with Image.open(odp.cesta) as img:
                tp.cerne_bloky_sken = cerne_bloky(img)
        tp.verze_detekce = VERZE_DETEKCE
    else:
        tp = extrahuj(Path(odp.cesta), nazev, int(ctx.metodika["p1"]["max_stran_ocr"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(asdict(tp), ensure_ascii=False), encoding="utf-8")
    return tp


def _stahni_prilohu(ctx: Kontext, zdroj: str, hs: HlidacRS | None, oficialni: OficialniRS | None,
                    z: ZaznamRS, pr: PrilohaRS) -> Odpoved | None:
    if zdroj == "hlidac":
        return hs.kopie_prilohy(z.id_verze, pr)
    try:
        return oficialni.priloha(pr)
    except NeshodaHashe as e:  # neshoda se níže zapíše jako shoda_hashe=False a příloha se nezpracuje
        return e.odpoved


def zpracuj(ctx: Kontext, zdroj: str, z: ZaznamRS, odp: Odpoved, hs: HlidacRS | None, oficialni: OficialniRS | None) -> tuple[dict, list[dict]]:
    rid = raw.zapis_zaznam(
        ctx.conn, zdroj=z.zdroj, id_ve_zdroji=z.id_verze, url=odp.url, cas_stazeni=odp.cas_stazeni,
        obsah=z.jako_dict(), format="html" if zdroj == "hlidac" else "xml", stazeni_id=odp.stazeni_id,
    )
    prilohy = []
    texty: list[str] = []
    odkaz_originalu = None
    znecitelneni: list[str] = []
    for pr in z.prilohy[:MAX_PRILOH]:
        info = {"nazev_ma_znacku": bool(a.RE_NAZEV_ZNECITELNENI.search(pr.nazev or "")), "sha256_metadata": pr.sha256}
        if info["nazev_ma_znacku"]:
            znecitelneni.append("název souboru")
        o = _stahni_prilohu(ctx, zdroj, hs, oficialni, z, pr)
        if o is None or not o.ok:
            info["stav"] = f"nestazeno ({o.status if o else 'bez odkazu'})"
            prilohy.append(info)
            continue
        info["velikost"] = o.cesta.stat().st_size
        info["sha256_stazeno"] = o.sha256
        info["shoda_hashe"] = (pr.sha256 == o.sha256) if pr.sha256 else None
        raw.zapis_zaznam(
            ctx.conn, zdroj=z.zdroj, id_ve_zdroji=f"{z.id_verze}/priloha/{o.sha256}", url=o.url,
            cas_stazeni=o.cas_stazeni, format="binarni", stazeni_id=o.stazeni_id,
            obsah={"id_verze": z.id_verze, "nazev": pr.nazev, "url_original": pr.url_original,
                   "sha256_metadata": pr.sha256, "sha256_stazeno": o.sha256, "shoda_hashe": info["shoda_hashe"],
                   "soubor": str(o.cesta.relative_to(ctx.nast.data_dir / "raw")), "velikost": info["velikost"]},
        )
        if info["shoda_hashe"] is False:
            info["stav"] = "hash_nesouhlasi"  # soubor nelze považovat za originál -> nepoužije se
            prilohy.append(info)
            continue
        if info["velikost"] > MAX_VELIKOST_PRILOHY:
            info["stav"] = "prilis_velka"
            prilohy.append(info)
            continue
        tp = text_prilohy(ctx, o, pr.nazev)
        info.update({"stav": "zpracovano", "format": tp.format, "metoda": tp.metoda, "stran": tp.stran,
                     "ocr_stran": tp.ocr_stran, "citelny": tp.citelny, "cerne_obdelniky": tp.cerne_obdelniky,
                     "cerne_bloky_sken": tp.cerne_bloky_sken, "orezano": tp.orezano})
        if tp.citelny:
            texty.append(tp.text)
            odkaz_originalu = odkaz_originalu or pr.url_original
            znacky = a.znacky_znecitelneni(tp.text)
            if znacky:
                znecitelneni.append("textové značky")
                info["znacky"] = len(znacky)
        if tp.cerne_obdelniky:
            znecitelneni.append("černé obdélníky v PDF")
        if tp.cerne_bloky_sken:
            znecitelneni.append("černé bloky ve skenu")
        prilohy.append(info)
    ctx.conn.commit()

    strany_ico = [s for s in z.smluvni_strany if s.ico_platne]
    vysledek = {
        "id_verze": z.id_verze,
        "id_smlouvy": z.id_smlouvy,
        "odkaz": z.odkaz,
        "zdroj": z.zdroj,
        "raw_zaznam_id": rid,
        "cas_zverejneni": z.cas_zverejneni,
        "datum_uzavreni": z.datum_uzavreni,
        "ico_subjektu": bool(z.subjekt and z.subjekt.ico_platne),
        "ico_protistrany": bool(strany_ico),
        "pocet_protistran": len(z.smluvni_strany),
        "protistran_bez_ico": sum(1 for s in z.smluvni_strany if not s.ico),
        "castka_v_metadatech": z.ma_castku,
        "hodnota_bez_dph": z.hodnota_bez_dph,
        "hodnota_vcetne_dph": z.hodnota_vcetne_dph,
        "cizi_mena": z.cizi_mena,
        "duvod_neuvedeni_ceny": bool(z.duvod_neuvedeni_ceny),
        "prilohy": prilohy,
        "text_citelny": bool(texty),
        "znecitelneni": sorted(set(znecitelneni)),
    }
    vysledek["m1_ico_obe_strany_a_castka"] = vysledek["ico_subjektu"] and vysledek["ico_protistrany"] and z.ma_castku
    vyjimky: list[dict] = []
    text = "\n\f".join(texty)
    castky_textu = a.najdi_castky(text) if text else []
    cenove = a.ceny_plneni(text, castky_textu)
    vysledek["castka_v_priloze"] = bool(cenove)
    vysledek["m2_castka_jen_v_priloze"] = (not z.ma_castku) and bool(cenove)
    vysledek["m3_znecitelneno"] = bool(znecitelneni)
    if text:
        kontroly, vyjimky = krizova_kontrola(z, TextZaznamu(text, odkaz_originalu))
        vysledek["kontroly"] = kontroly
    else:
        vysledek["kontroly"] = None
    return vysledek, vyjimky


def mer(ctx: Kontext) -> dict:
    n = int(ctx.metodika["p1"]["n"])
    zdroj, info_zdroje = zvol_zdroj(ctx)
    LOG.info("P1: zdroj registru smluv = %s", zdroj)
    hs = HlidacRS(ctx.stahovac, pilot=True)
    oficialni = OficialniRS(ctx.stahovac)
    if zdroj == "oficialni":
        vzorek = [(z, odp) for z, _xml, odp in oficialni.vzorek(n, ctx.od, ctx.do, ctx.rng("p1").randrange(2**31))]
        stat_vyberu = {"metoda": "denni_dumpy"}
    else:
        vzorek, stat_vyberu = vzorek_hlidac(ctx, hs, n)
        stat_vyberu["metoda"] = "skupiny_id_zrcadlo"
    polozky, vyjimky = [], []
    for i, (z, odp) in enumerate(vzorek, 1):
        v, vy = zpracuj(ctx, zdroj, z, odp, hs, oficialni)
        polozky.append(v)
        vyjimky += vy
        if i % 10 == 0:
            LOG.info("P1 zpracováno %d/%d", i, len(vzorek))
    pocet = len(polozky)

    def podil(klic: str) -> dict:
        return Podil(sum(1 for p in polozky if p[klic]), pocet).jako_dict()

    bez_castky = [p for p in polozky if not p["castka_v_metadatech"]]
    citelne = [p for p in polozky if p["text_citelny"]]
    vysledky = {
        "zdroj": zdroj,
        "info_zdroje": info_zdroje,
        "vyber": stat_vyberu,
        "n": pocet,
        "m1_ico_obe_strany_a_castka": podil("m1_ico_obe_strany_a_castka"),
        "m2_castka_jen_v_priloze": podil("m2_castka_jen_v_priloze"),
        "m3_znecitelneno": podil("m3_znecitelneno"),
        "rozpad": {
            "ico_subjektu": podil("ico_subjektu"),
            "ico_protistrany": podil("ico_protistrany"),
            "castka_v_metadatech": podil("castka_v_metadatech"),
            "duvod_neuvedeni_ceny": podil("duvod_neuvedeni_ceny"),
            "text_citelny": podil("text_citelny"),
            "m2_mezi_bez_castky": Podil(sum(1 for p in bez_castky if p["m2_castka_jen_v_priloze"]), len(bez_castky)).jako_dict(),
            "m3_mezi_citelnymi": Podil(sum(1 for p in citelne if p["m3_znecitelneno"]), len(citelne)).jako_dict(),
        },
        "polozky": polozky,
        "vyjimky": vyjimky,
    }
    ctx.uloz("p1", vysledky)
    return vysledky


def mer_metadata(ctx: Kontext) -> dict:
    """Přeměření P1 po pilotu jen z metadat (bez stahování a čtení příloh; křížová kontrola s textem
    proběhla v pilotu). Výběr je stejný postup se stejným seedem, prvních n pilotu je jeho prefixem."""
    n = int(ctx.metodika["p1_metadata"]["n"])
    zdroj, info_zdroje = zvol_zdroj(ctx)
    LOG.info("P1 metadata: zdroj registru smluv = %s, n = %d", zdroj, n)
    if zdroj == "oficialni":
        oficialni = OficialniRS(ctx.stahovac)
        vzorek = [(z, odp) for z, _xml, odp in oficialni.vzorek(n, ctx.od, ctx.do, ctx.rng("p1").randrange(2**31))]
        stat_vyberu = {"metoda": "denni_dumpy"}
    else:
        vzorek, stat_vyberu = vzorek_hlidac(ctx, HlidacRS(ctx.stahovac, pilot=True), n)
        stat_vyberu["metoda"] = "skupiny_id_zrcadlo"
    polozky = []
    for z, _odp in vzorek:
        polozky.append({
            "id_verze": z.id_verze,
            "odkaz": z.odkaz,
            "ico_subjektu": bool(z.subjekt and z.subjekt.ico_platne),
            "ico_protistrany": any(s.ico_platne for s in z.smluvni_strany),
            "castka_v_metadatech": z.ma_castku,
            "duvod_neuvedeni_ceny": bool(z.duvod_neuvedeni_ceny),
        })
        p = polozky[-1]
        p["m1_ico_obe_strany_a_castka"] = p["ico_subjektu"] and p["ico_protistrany"] and p["castka_v_metadatech"]
    pocet = len(polozky)

    def podil(klic: str) -> dict:
        return Podil(sum(1 for p in polozky if p[klic]), pocet).jako_dict()

    vysledky = {
        "zdroj": zdroj,
        "info_zdroje": info_zdroje,
        "vyber": stat_vyberu,
        "n": pocet,
        "m1_ico_obe_strany_a_castka": podil("m1_ico_obe_strany_a_castka"),
        "rozpad": {k: podil(k) for k in ("ico_subjektu", "ico_protistrany", "castka_v_metadatech",
                                         "duvod_neuvedeni_ceny")},
        "polozky": polozky,
    }
    LOG.info("P1 metadata: %d záznamů, IČO obou stran i částka %s", pocet, vysledky["m1_ico_obe_strany_a_castka"])
    ctx.uloz("p1_metadata", vysledky)
    return vysledky
