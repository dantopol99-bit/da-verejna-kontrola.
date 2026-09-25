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


def klasifikuj(text: str, min_dni: int = 366) -> dict:
    """Čistá funkce: text smlouvy -> {opakovane, verdikt, rocni_hodnota, duvod, dukazy}."""
    doba = a.doba_plneni(text)
    castky = a.najdi_castky(text)
    periodicke = a.periodicke_castky(text, castky)
    opakovane_slovo = a.RE_OPAKOVANE_PLNENI.search(text)
    viceleta = doba["delka_dni"] is not None and doba["delka_dni"] >= min_dni
    ma_periodu = any(periodicke.values())
    opakovane = bool(doba["neurcita"]) or viceleta or ma_periodu or bool(opakovane_slovo)
    vysledek: dict = {
        "opakovane": opakovane,
        "neurcita": doba["neurcita"],
        "delka_dni": doba["delka_dni"],
        "periodicke": {k: sorted({str(n.hodnota) for n in v}) for k, v in periodicke.items()},
        "verdikt": None,
        "rocni_hodnota": None,
        "duvod": None,
        "dukazy": doba["dukaz"][:2],
    }
    if not opakovane:
        return vysledek

    def jednoznacna(nalezy: list[a.NalezCastky]) -> Decimal | None:
        hodnoty = {n.hodnota for n in nalezy}
        return hodnoty.pop() if len(hodnoty) == 1 else None

    druhy = [k for k, v in periodicke.items() if v]
    if len(druhy) == 1:
        nalezy = periodicke[druhy[0]]
        hodnota = jednoznacna(nalezy)
        if hodnota is not None:
            nasobek = {"rocni": 1, "mesicni": 12, "ctvrtletni": 4}[druhy[0]]
            vysledek.update(verdikt="ano", rocni_hodnota=hodnota * nasobek,
                            duvod=f"jednoznačná {druhy[0]} částka", dukazy=[nalezy[0].uryvek])
            return vysledek
        vysledek.update(verdikt="nejasne", duvod=f"více různých částek s periodou {druhy[0]}",
                        dukazy=[n.uryvek for n in nalezy[:2]])
        return vysledek
    if len(druhy) > 1:
        vysledek.update(verdikt="nejasne", duvod="částky s různými periodami (" + ", ".join(druhy) + ")",
                        dukazy=[n.uryvek for k in druhy for n in periodicke[k][:1]])
        return vysledek
    # bez periodické částky
    celkem = a.RE_CELKEM_ZA_DOBU.search(text)
    cenove = [c for c in castky if c.cenovy_kontext]
    if celkem and viceleta and not doba["neurcita"] and cenove:
        hodnota = max(c.hodnota for c in cenove)
        let = Decimal(doba["delka_dni"]) / Decimal(365)
        vysledek.update(verdikt="ano", rocni_hodnota=(hodnota / let).quantize(Decimal("0.01")),
                        duvod="celková cena výslovně za celou dobu trvání a pevná doba trvání",
                        dukazy=[a.uryvek(text, celkem.start(), celkem.end())])
        return vysledek
    if a.RE_JEDNOTKOVA.search(text) and not cenove:
        vysledek.update(verdikt="ne", duvod="jen jednotkové ceny bez objemu")
    elif doba["neurcita"]:
        vysledek.update(verdikt="ne", duvod="doba neurčitá bez periodické částky")
    elif not cenove:
        vysledek.update(verdikt="ne", duvod="text neuvádí částku v cenovém kontextu")
    elif viceleta:
        vysledek.update(verdikt="nejasne", duvod="víceletá smlouva s celkovou cenou bez výslovné vazby na dobu trvání")
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
