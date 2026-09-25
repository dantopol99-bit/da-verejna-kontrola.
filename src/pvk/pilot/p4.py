"""P4 – příjemci dotací: podíl spárovatelných na IČO přes ARES (vzorek z každého registru).

Kategorie párování (z nich se počítají podíly):
  ico_ares_shoda_nazvu     IČO existuje v ARES a název odpovídá (podobnost >= prah)   -> spárovatelné
  ico_ares_jiny_nazev      IČO existuje v ARES, název neodpovídá (přejmenování / chyba) -> spárovatelné s výhradou
  ico_neexistuje_v_ares    IČO má správný tvar, ale ARES ho nezná                      -> nespárovatelné
  ico_neplatne             IČO nemá platnou kontrolní číslici                          -> nespárovatelné
  nazev_ares_jednoznacne   bez IČO (právnická osoba), ARES najde jednoznačně podle názvu -> spárovatelné
  nazev_ares_nejednoznacne bez IČO, více kandidátů                                     -> nespárovatelné
  bez_ico_nenalezeno       bez IČO, ARES nic nenajde                                   -> nespárovatelné
  fo_bez_ico               fyzická osoba bez IČO – mimo rozsah platformy, z definice    -> nespárovatelné
Fyzické osoby bez IČO se nelosují: jejich podíl se spočítá přesně na celém rámci (slozeni_ramce),
vzorek pro párování je z příjemců v rozsahu (právnické osoby a podnikající fyzické osoby s IČO).
Do výstupů se nepřebírají údaje z ARES (jen kategorie a skóre podobnosti).
"""

from __future__ import annotations

from pvk import raw
from pvk.ico import ico_platne
from pvk.kotva import AresKotva, Kotva
from pvk.pilot.kontext import LOG, Kontext
from pvk.pilot.nazvy import podobnost
from pvk.pilot.statistika import Podil
from pvk.zdroje.dotace import SZIF, Prijemce, ReD, SeznamOperaci

SPAROVATELNE = {"ico_ares_shoda_nazvu", "nazev_ares_jednoznacne"}
SPAROVATELNE_S_VYHRADOU = {"ico_ares_jiny_nazev"}


def sparuj(p: Prijemce, kotva: Kotva, prah: float) -> dict:
    vysledek = {"kategorie": None, "podobnost_nazvu": None, "ico": p.ico, "je_fyzicka_osoba": p.je_fyzicka_osoba}
    if p.ico:
        if not ico_platne(p.ico):
            vysledek["kategorie"] = "ico_neplatne"
            return vysledek
        s = kotva.subjekt_podle_ico(p.ico)
        if s is None:
            vysledek["kategorie"] = "ico_neexistuje_v_ares"
            return vysledek
        if p.je_fyzicka_osoba or not p.nazev:
            # název fyzické osoby do raw neukládáme; u FO s IČO stačí existence IČO + právní forma FO v ARES
            vysledek["podobnost_nazvu"] = None
            vysledek["kategorie"] = "ico_ares_shoda_nazvu" if (s.je_fyzicka_osoba or not p.nazev) else "ico_ares_jiny_nazev"
            return vysledek
        pod = podobnost(p.nazev, s.nazev)
        vysledek["podobnost_nazvu"] = round(pod, 3)
        vysledek["kategorie"] = "ico_ares_shoda_nazvu" if pod >= prah else "ico_ares_jiny_nazev"
        return vysledek
    if p.je_fyzicka_osoba:
        vysledek["kategorie"] = "fo_bez_ico"
        return vysledek
    kandidati = [k for k in kotva.hledej_podle_nazvu(p.nazev or "", 5) if podobnost(p.nazev, k.nazev) >= prah]
    if len(kandidati) == 1:
        vysledek["kategorie"] = "nazev_ares_jednoznacne"
        vysledek["podobnost_nazvu"] = round(podobnost(p.nazev, kandidati[0].nazev), 3)
    elif kandidati:
        vysledek["kategorie"] = "nazev_ares_nejednoznacne"
    else:
        vysledek["kategorie"] = "bez_ico_nenalezeno"
    return vysledek


def slozeni_ramce(ramec: list[Prijemce]) -> dict[str, int]:
    """Přesné složení celého rámce (bez výběru): fyzické / právnické osoby s IČO a bez IČO."""
    slozeni = {"fo_bez_ico": 0, "fo_s_ico": 0, "po_s_ico": 0, "po_bez_ico": 0}
    for p in ramec:
        slozeni[("fo" if p.je_fyzicka_osoba else "po") + ("_s_ico" if p.ico else "_bez_ico")] += 1
    return slozeni


def _vyber_a_sparuj(ctx: Kontext, registr: str, ramec: list[Prijemce], meta: dict, kotva: Kotva) -> dict:
    """Fyzické osoby bez IČO jsou mimo rozsah platformy a z definice nespárovatelné: jejich podíl se
    spočítá přesně na celém rámci; vzorek pro párování se losuje z příjemců v rozsahu (D-016)."""
    n = int(ctx.metodika["p4"]["n_na_registr"])
    prah = float(ctx.metodika["p4"]["prah_podobnosti_nazvu"])
    slozeni = slozeni_ramce(ramec)
    v_rozsahu = [p for p in ramec if not (p.je_fyzicka_osoba and not p.ico)]
    vzorek = ctx.rng(f"p4:{registr}:v_rozsahu").sample(v_rozsahu, min(n, len(v_rozsahu)))
    polozky = []
    for i, p in enumerate(vzorek, 1):
        rid = raw.zapis_zaznam(
            ctx.conn,
            zdroj=p.registr,
            id_ve_zdroji=p.id_ve_zdroji,
            url=p.zaznam.get("_url_souboru") or meta.get("soubor") or "",
            cas_stazeni=meta["cas_stazeni"],
            obsah={k: v for k, v in p.zaznam.items() if not k.startswith("_")},
            format="csv" if p.registr == "red" else "xlsx",
            stazeni_id=meta.get("stazeni_id"),
            redigovat=p.redigovat,
        )
        ctx.conn.commit()
        v = sparuj(p, kotva, prah)
        polozky.append({"raw_zaznam_id": rid, "id_ve_zdroji": p.id_ve_zdroji if not p.je_fyzicka_osoba else "FO",
                        "pravni_forma": p.pravni_forma, **v})
        if i % 50 == 0:
            LOG.info("P4 %s: %d/%d", registr, i, len(vzorek))
    kategorie: dict[str, int] = {}
    for x in polozky:
        kategorie[x["kategorie"]] = kategorie.get(x["kategorie"], 0) + 1
    sparovatelne = sum(1 for x in polozky if x["kategorie"] in SPAROVATELNE)
    s_vyhradou = sum(1 for x in polozky if x["kategorie"] in SPAROVATELNE | SPAROVATELNE_S_VYHRADOU)
    return {
        "registr": registr,
        "stav": "zmereno",
        "meta": meta,
        "slozeni_ramce": slozeni,
        "ramec_v_rozsahu": len(v_rozsahu),
        "podil_fo_bez_ico_v_ramci": Podil(slozeni["fo_bez_ico"], len(ramec)).jako_dict(),
        "n": len(polozky),
        "kategorie": kategorie,
        "sparovatelne": Podil(sparovatelne, len(polozky)).jako_dict(),
        "sparovatelne_vcetne_jineho_nazvu": Podil(s_vyhradou, len(polozky)).jako_dict(),
        "polozky": polozky,
    }


def _meta_stazeni(ctx: Kontext, url: str) -> dict:
    row = ctx.conn.execute(
        "SELECT id, cas_stazeni, sha256, hlavicky FROM raw.stazeni WHERE url = %s AND http_status = 200 "
        "ORDER BY cas_stazeni DESC LIMIT 1",
        (url,),
    ).fetchone()
    return {"stazeni_id": row["id"], "cas_stazeni": row["cas_stazeni"], "last_modified": (row["hlavicky"] or {}).get("last-modified")}


def mer(ctx: Kontext, kotva: Kotva | None = None) -> dict:
    kotva = kotva or AresKotva(ctx.nast.user_agent)
    vysledky = {}

    LOG.info("P4: IS ReD – rámec příjemců")
    try:
        ramec, meta = ReD(ctx.stahovac).prijemci_s_dotaci(365)
        meta.update(_meta_stazeni(ctx, meta["soubor_prijemce"]))
        vysledky["red"] = _vyber_a_sparuj(ctx, "red", ramec, meta, kotva)
    except Exception as e:  # zdroj nedostupný: zaznamenat, nepřerušit pilot
        LOG.exception("P4 ReD selhalo")
        vysledky["red"] = {"registr": "red", "stav": "nedostupne", "chyba": f"{type(e).__name__}: {e}"}

    LOG.info("P4: Seznam operací 2021–2027")
    try:
        ramec, meta = SeznamOperaci(ctx.stahovac).prijemci()
        meta.update(_meta_stazeni(ctx, meta["soubor"]))
        vysledky["dotaceeu_2127"] = _vyber_a_sparuj(ctx, "dotaceeu_2127", ramec, meta, kotva)
    except Exception as e:
        LOG.exception("P4 dotaceeu selhalo")
        vysledky["dotaceeu_2127"] = {"registr": "dotaceeu_2127", "stav": "nedostupne", "chyba": f"{type(e).__name__}: {e}"}

    LOG.info("P4: SZIF")
    odp, stav = SZIF(ctx.stahovac).zkus_stahnout()
    vysledky["szif"] = {
        "registr": "szif",
        "stav": "nedostupne" if stav != "ok" else "stazeno_nezpracovano",
        "duvod": {
            "antibot": "server vrací JavaScriptovou anti-bot výzvu (F5 TSPD) místo dat; ochranu neobcházíme",
            "nedostupne": f"HTTP {odp.status} {odp.chyba or ''}".strip(),
            "ok": "data stažena",
        }[stav],
        "url": odp.url,
        "cas": odp.cas_stazeni,
        "stazeni_id": odp.stazeni_id,
    }
    ctx.uloz("p4", vysledky)
    return vysledky
