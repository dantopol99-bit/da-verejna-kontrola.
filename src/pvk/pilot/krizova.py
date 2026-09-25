"""Křížová kontrola P1: metadata registru smluv × text originálu přílohy.

Kontroluje se:
  castka          metadata (bez DPH / s DPH) se najdou v textu (tolerance 1 Kč; přepočet DPH 21/12/15/10 %),
                  případně jsou násobkem periodické částky (12–60 měsíců) nebo součtem 2–3 položek textu
  ico             IČO publikujícího subjektu a smluvních stran se najdou v textu
  datum_uzavreni  datum uzavření z metadat je v textu; jinak se porovná s posledním datem podpisu
  castka_chybi    metadata neuvádějí částku, ale text ji uvádí (= "částka jen v příloze")
Neshody se zapisují jako výjimky s návrhem verdiktu k potvrzení (docs/pilot_vyjimky.csv).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pvk.ico import ico_platne
from pvk.text import analyza as a
from pvk.zdroje.rs import ZaznamRS

SAZBY_DPH = (Decimal("0.21"), Decimal("0.12"), Decimal("0.15"), Decimal("0.10"))


@dataclass
class TextZaznamu:
    """Spojený čitelný text příloh jednoho záznamu + odkaz na originál, ze kterého pochází."""

    text: str
    odkaz_originalu: str | None


def _fmt(h: Decimal | None) -> str:
    if h is None:
        return ""
    return f"{h:,.2f}".replace(",", " ").replace(".", ",") + " Kč"


def _popis(n: a.NalezCastky) -> str:
    """Částka z textu bez citace okolního textu (citace mohou obsahovat osobní údaje);
    jen klíčové slovo, podle kterého byl kontext označen jako cenový."""
    return f"{_fmt(n.hodnota) if n.mena == 'CZK' else f'{n.hodnota} {n.mena}'} (kontext: {n.klicove_slovo or '–'})"


def kontrola_castky(z: ZaznamRS, nalezy: list[a.NalezCastky], text: str = "") -> tuple[str, str | None, list[a.NalezCastky]]:
    """Vrací (výsledek, důkaz, kandidáti z textu). Výsledek: shoda | shoda_po_prepoctu_dph |
    shoda_nasobek_periody | shoda_souctu_polozek | neshoda | text_bez_ceny | bez_castky_v_metadatech | cizi_mena."""
    cenove = a.ceny_plneni(text, nalezy)
    if not z.ma_castku:
        return "bez_castky_v_metadatech", None, cenove
    if z.hodnota_bez_dph is None and z.hodnota_vcetne_dph is None:
        n = a.castka_v_textu(z.cizi_mena_hodnota, [x for x in nalezy if x.mena == z.cizi_mena]) if z.cizi_mena_hodnota else None
        return ("shoda", n.uryvek, cenove) if n else ("cizi_mena", None, cenove)
    for hodnota in (z.hodnota_bez_dph, z.hodnota_vcetne_dph):
        if hodnota is not None:
            n = a.castka_v_textu(hodnota, nalezy)
            if n:
                return "shoda", n.uryvek, cenove
            nalez = a.hodnota_v_textu(hodnota, text)  # číslo bez označení měny (tabulky)
            if nalez:
                return "shoda", nalez, cenove
    for hodnota in (z.hodnota_bez_dph, z.hodnota_vcetne_dph):
        if hodnota is None:
            continue
        for sazba in SAZBY_DPH:
            for prepocet in (hodnota * (1 + sazba), hodnota / (1 + sazba)):
                prepocet = prepocet.quantize(Decimal("0.01"))
                n = a.castka_v_textu(prepocet, nalezy, tolerance_kc=Decimal(2))
                if n:
                    return "shoda_po_prepoctu_dph", n.uryvek, cenove
                nalez = a.hodnota_v_textu(prepocet, text)
                if nalez:
                    return "shoda_po_prepoctu_dph", nalez, cenove
    if not cenove:
        return "text_bez_ceny", None, cenove
    vysvetleni = vysvetlitelna_castka(z, cenove)
    if vysvetleni:
        return vysvetleni[0], vysvetleni[1], cenove
    return "neshoda", None, cenove


NASOBKY_PERIODY = (12, 24, 36, 48, 60)  # 60 = konvence RS "hodnota za 5 let" u doby neurčité
MAX_POLOZEK_SOUCTU = 15


def vysvetlitelna_castka(z: ZaznamRS, cenove: list[a.NalezCastky]) -> tuple[str, str] | None:
    """Metadata = N × periodická částka z textu, nebo součet 2–3 cenových položek z textu (±1 Kč).
    Vrací (výsledek, vysvětlení) nebo None."""
    from itertools import combinations

    metadata = [h for h in (z.hodnota_bez_dph, z.hodnota_vcetne_dph) if h is not None]
    hodnoty = sorted({n.hodnota for n in cenove if n.mena == "CZK"})
    for m in metadata:
        for h in hodnoty:
            for nasobek in NASOBKY_PERIODY:
                if abs(h * nasobek - m) <= 1:
                    return "shoda_nasobek_periody", f"{_fmt(m)} = {nasobek} × {_fmt(h)}"
    polozky = hodnoty[:MAX_POLOZEK_SOUCTU]
    for m in metadata:
        for k in (2, 3):
            for kombinace in combinations(polozky, k):
                if abs(sum(kombinace) - m) <= 1:
                    return "shoda_souctu_polozek", f"{_fmt(m)} = " + " + ".join(_fmt(x) for x in kombinace)
    return None


def jina_ica_v_textu(text: str, znama: set[str]) -> list[str]:
    import re

    nalezena = []
    for m in re.finditer(r"IČ[OZ]?\s*:?\s*(\d{3}\s?\d{2}\s?\d{3}|\d{8})(?!\d)", text):
        ico = re.sub(r"\s", "", m.group(1))
        if ico_platne(ico) and ico not in znama and ico not in nalezena:
            nalezena.append(ico)
    return nalezena


def krizova_kontrola(z: ZaznamRS, tz: TextZaznamu) -> tuple[dict, list[dict]]:
    """Vrací (výsledky kontrol, výjimky)."""
    text = tz.text
    vyjimky: list[dict] = []
    vysledky: dict = {}

    def vyjimka(udaj: str, metadata: str, v_textu: str, verdikt: str, zduvodneni: str) -> None:
        vyjimky.append({
            "zaznam": z.id_verze,
            "udaj": udaj,
            "hodnota_metadata": metadata,
            "nalezeno_v_textu": v_textu,
            "odkaz_zaznamu": z.odkaz,
            "odkaz_originalu": tz.odkaz_originalu or "",
            "navrh_verdiktu": verdikt,
            "zduvodneni": zduvodneni,
        })

    # --- částka ---
    nalezy = a.najdi_castky(text)
    vysledek, dukaz, cenove = kontrola_castky(z, nalezy, text)
    vysledky["castka"] = vysledek
    vysledky["castka_dukaz"] = dukaz
    kandidati = sorted(cenove, key=lambda n: -n.hodnota)[:3]
    if vysledek == "neshoda":
        vyjimka(
            "castka",
            f"bez DPH {_fmt(z.hodnota_bez_dph)}; s DPH {_fmt(z.hodnota_vcetne_dph)}".strip("; "),
            "; ".join(_popis(n) for n in kandidati),
            "NESHODA – ověřit; pokud je v textu cena celého plnění, metadata jsou chybná",
            "částka z metadat se v textu nenachází ani po přepočtu DPH; text uvádí jiné částky v cenovém kontextu",
        )
    elif vysledek == "bez_castky_v_metadatech" and cenove:
        n = max(cenove, key=lambda x: x.hodnota)
        vyjimka(
            "castka_chybi_v_metadatech",
            ("neuvedena; důvod: " + z.duvod_neuvedeni_ceny) if z.duvod_neuvedeni_ceny else "neuvedena",
            _popis(n),
            "ČÁSTKA JEN V PŘÍLOZE – potvrdit, že jde o cenu plnění",
            "metadata částku neuvádějí, text přílohy ji uvádí v cenovém kontextu",
        )

    # --- IČO ---
    ica = {}
    strany = ([("subjekt", z.subjekt)] if z.subjekt else []) + [("strana", s) for s in z.smluvni_strany]
    znama = {s.ico for _, s in strany if s.ico}
    jina = jina_ica_v_textu(text, znama)
    nalezena = {ico for ico in znama if a.ico_v_textu(ico, text)}
    for role, s in strany:
        if not s.ico:
            continue
        ica[s.ico] = "nalezeno" if s.ico in nalezena else "nenalezeno"
        if s.ico not in nalezena:
            if jina:
                verdikt = "NESHODA IČO – ověřit; text uvádí jiné platné IČO"
                duvod = "IČO z metadat v textu chybí, text obsahuje jiné platné IČO: " + ", ".join(jina[:3])
            elif nalezena:
                verdikt = "NELZE OVĚŘIT – text uvádí jen IČO jiné strany z metadat; metadata ponechat"
                duvod = "text uvádí IČO jiné strany z metadat, toto IČO ani žádné další IČO neuvádí"
            else:
                verdikt = "NELZE OVĚŘIT – text přílohy neuvádí žádné IČO; metadata ponechat"
                duvod = "text přílohy neuvádí žádné IČO (např. objednávka, ceník, dopis bez identifikace stran)"
            vyjimka(f"ico_{role}", s.ico, ", ".join(jina[:3]) or "—", verdikt, duvod)
    vysledky["ico"] = ica

    # --- datum uzavření ---
    # Smlouva je uzavřena posledním podpisem. Rozpor = metadata uvádějí datum dřívější, než je poslední
    # datum podpisu v textu. Je-li datum v metadatech pozdější než všechna data podpisu v textu, mohl
    # poslední podpis proběhnout bez uvedeného data (nelze ověřit).
    data = a.najdi_data(text)
    podpisy = sorted({d.datum for d in data if d.podpis
                      and (z.cas_zverejneni is None or d.datum <= z.cas_zverejneni.date())})
    if z.datum_uzavreni is None:
        vysledky["datum_uzavreni"] = "bez_data_v_metadatech"
    elif z.datum_uzavreni in podpisy:
        vysledky["datum_uzavreni"] = "shoda"
    elif podpisy and podpisy[-1] > z.datum_uzavreni:
        vysledky["datum_uzavreni"] = "neshoda"
        vyjimka(
            "datum_uzavreni",
            z.datum_uzavreni.isoformat(),
            ", ".join(x.isoformat() for x in podpisy[-3:]),
            f"NESHODA – navrhuji datum posledního podpisu {podpisy[-1].isoformat()}",
            "metadata uvádějí datum uzavření dřívější než poslední datum podpisu v textu smlouvy",
        )
    elif any(d.datum == z.datum_uzavreni for d in data):
        vysledky["datum_uzavreni"] = "shoda"  # datum je v textu, jen ne v kontextu podpisu
    else:
        vysledky["datum_uzavreni"] = "nelze_overit"
    return vysledky, vyjimky
