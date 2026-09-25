"""P3 – smlouvy s opakovaným / víceletým plněním ve vzorku P1: lze spolehlivě určit roční hodnotu?

Krok 1 – je plnění opakované nebo víceleté? (z textu příloh)
  * smlouva na dobu neurčitou (ve větě o smlouvě/nájmu/objednávce), nebo
  * doba plnění delší než rok (po dobu N let/měsíců, od–do), nebo
  * periodická částka (měsíčně / ročně / čtvrtletně) nebo typicky opakované plnění (nájem, pacht,
    předplatné, paušál, pravidelný servis).
Krok 2 – verdikt:
  ano      text uvádí částku za rok, nebo jednoznačně přepočitatelnou měsíční/čtvrtletní částku
           (všechny periodické částky téhož druhu mají stejnou hodnotu), nebo celkovou cenu výslovně
           za celou dobu trvání spolu s pevnou délkou trvání
  ne       doba neurčitá bez periodické částky, jen jednotkové ceny, nebo žádná částka
  nejasne  protichůdné signály (různé periodické částky), nečitelný text
"""

from __future__ import annotations

import json
from decimal import Decimal

from pvk.pilot.kontext import LOG, Kontext
from pvk.pilot.statistika import Podil
from pvk.text import analyza as a
from pvk.text.extrakce import TextPrilohy


def _text_zaznamu(ctx: Kontext, polozka: dict) -> str | None:
    texty = []
    for pr in polozka["prilohy"]:
        sha = pr.get("sha256_stazeno")
        if pr.get("stav") != "zpracovano" or not pr.get("citelny") or not sha:
            continue
        cache = ctx.nast.data_dir / "cache" / "text" / f"{sha}.json"
        if cache.is_file():
            texty.append(TextPrilohy(**json.loads(cache.read_text(encoding="utf-8"))).text)
    return "\n\f".join(texty) if texty else None


NASOBKY = {"rocni": 1, "mesicni": 12, "ctvrtletni": 4}
NAZVY_PERIOD = {"rocni": "roční", "mesicni": "měsíční", "ctvrtletni": "čtvrtletní"}
SAZBY_DPH = (Decimal("0.21"), Decimal("0.12"))


def sluc_dph(hodnoty: set[Decimal]) -> set[Decimal]:
    """Sloučí varianty téže částky: s DPH (×1,21 / ×1,12) a samotnou DPH (×0,21 / ×0,12) nahradí
    základem bez DPH. {11 880 000, 14 374 800, 2 494 800} -> {11 880 000}."""
    odvozene = set()
    for w in hodnoty:
        for v in hodnoty:
            if v == w:
                continue
            if any(abs(w - v * (1 + s)) <= 1 or abs(w - v * s) <= 1 for s in SAZBY_DPH):
                odvozene.add(w)
    return set(hodnoty) - odvozene


def klasifikuj(text: str, min_dni: int = 366) -> dict:
    """Čistá funkce: text smlouvy -> {opakovane, verdikt, rocni_hodnota, duvod, dukazy}."""
    doba = a.doba_plneni(text)
    castky = a.najdi_castky(text)
    periodicke = a.periodicke_castky(text, castky)
    opakovane_slovo = a.RE_OPAKOVANE_PLNENI.search(text)
    delka = doba["delka_dni"]
    viceleta = delka is not None and delka >= min_dni
    # průběžné plnění (služby, nájem…) trvající aspoň půl roku je opakované i v rámci jednoho roku
    prubezne = delka is not None and delka >= 180 and doba["prubezne"]
    druhy = [k for k, v in periodicke.items() if v]
    opakovane = bool(doba["neurcita"]) or viceleta or prubezne or bool(druhy) or bool(opakovane_slovo)
    vysledek: dict = {
        "opakovane": opakovane,
        "neurcita": doba["neurcita"],
        "delka_dni": delka,
        "periodicke": {k: sorted({str(n.hodnota) for n in v}) for k, v in periodicke.items()},
        "verdikt": None,
        "rocni_hodnota": None,
        "duvod": None,
        "dukazy": doba["dukaz"][:2],
    }
    if not opakovane:
        return vysledek

    if druhy:
        rocne = sluc_dph({n.hodnota * NASOBKY[k] for k in druhy for n in periodicke[k]})
        dukazy = [n.uryvek for k in druhy for n in periodicke[k][:1]]
        if len(rocne) == 1:
            (hodnota,) = rocne
            vysledek.update(verdikt="ano", rocni_hodnota=hodnota,
                            duvod="jednoznačná periodická částka (" + ", ".join(NAZVY_PERIOD[k] for k in druhy) + ")", dukazy=dukazy)
        else:
            vysledek.update(verdikt="nejasne", duvod="více různých periodických částek (" + ", ".join(NAZVY_PERIOD[k] for k in druhy) + ")",
                            dukazy=dukazy)
        return vysledek

    cenove = [c for c in a.ceny_plneni(text, castky) if c.hodnota >= a.MIN_PERIODICKA_CASTKA]
    if doba["neurcita"]:
        vysledek.update(verdikt="ne", duvod="doba neurčitá bez periodické částky")
    elif delka is not None and delka <= 370 and cenove:
        hodnota = max(sluc_dph({c.hodnota for c in cenove}))
        vysledek.update(verdikt="ano", rocni_hodnota=hodnota,
                        duvod="doba plnění nejvýš jeden rok – roční hodnota = cena za celé plnění")
    elif viceleta and cenove and a.RE_CELKEM_ZA_DOBU.search(text):
        celkem = max(sluc_dph({c.hodnota for c in cenove}))
        vysledek.update(verdikt="ano", rocni_hodnota=(celkem / (Decimal(delka) / Decimal(365))).quantize(Decimal("0.01")),
                        duvod="celková cena výslovně za celou dobu trvání a pevná doba trvání")
    elif a.RE_JEDNOTKOVA.search(text) and not cenove:
        vysledek.update(verdikt="ne", duvod="jen jednotkové ceny bez objemu")
    elif not cenove:
        vysledek.update(verdikt="ne", duvod="text neuvádí cenu plnění")
    elif viceleta:
        vysledek.update(verdikt="nejasne", duvod="víceletá smlouva s cenou bez výslovné vazby na dobu trvání")
    else:
        vysledek.update(verdikt="nejasne", duvod="opakované plnění bez údaje o periodě a délce")
    return vysledek


def mer(ctx: Kontext) -> dict:
    p1 = ctx.nacti("p1")
    if not p1:
        raise RuntimeError("P3 vyžaduje výsledky P1 (data/pilot/p1.json)")
    min_dni = int(ctx.metodika["p3"]["min_trvani_dni_viceleta"])
    polozky, vyjimky = [], []
    necitelne_opakovane_z_metadat = 0
    for p in p1["polozky"]:
        text = _text_zaznamu(ctx, p)
        if text is None:
            necitelne_opakovane_z_metadat += 1
            continue
        k = klasifikuj(text, min_dni)
        if not k["opakovane"]:
            continue
        polozky.append({"id_verze": p["id_verze"], "odkaz": p["odkaz"], **k})
        if k["verdikt"] == "nejasne":
            vyjimky.append({
                "zaznam": p["id_verze"],
                "udaj": "rocni_hodnota (P3)",
                "hodnota_metadata": f"bez DPH {p.get('hodnota_bez_dph') or '–'}; s DPH {p.get('hodnota_vcetne_dph') or '–'}",
                "nalezeno_v_textu": "; ".join(f"{k2}: {', '.join(v)}" for k2, v in k["periodicke"].items() if v) or "–",
                "odkaz_zaznamu": p["odkaz"],
                "odkaz_originalu": next((pr.get("url_original") or "" for pr in p["prilohy"] if pr.get("citelny")), ""),
                "navrh_verdiktu": "NEJASNÉ – roční hodnotu nelze spolehlivě určit",
                "zduvodneni": k["duvod"],
            })
    n = len(polozky)
    pocty = {v: sum(1 for x in polozky if x["verdikt"] == v) for v in ("ano", "ne", "nejasne")}
    vysledky = {
        "n_opakovane": n,
        "n_p1": len(p1["polozky"]),
        "bez_citelneho_textu": necitelne_opakovane_z_metadat,
        "pocty": pocty,
        "ano": Podil(pocty["ano"], n).jako_dict(),
        "ne": Podil(pocty["ne"], n).jako_dict(),
        "nejasne": Podil(pocty["nejasne"], n).jako_dict(),
        "polozky": polozky,
        "vyjimky": vyjimky,
    }
    LOG.info("P3: %d opakovaných/víceletých smluv, verdikty %s", n, pocty)
    ctx.uloz("p3", vysledky)
    return vysledky
