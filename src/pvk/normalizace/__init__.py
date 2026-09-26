"""Normalizace raw -> core (blok 3): IČO, typované částky, toky, vazby tok_zdroj a události.

Postup jednoho běhu (`python -m pvk.normalizace`, make normalizace):
  1. adaptéry zdrojů (pvk.normalizace.zdroje) převedou záznamy raw na normalizované záznamy
     (tok, částky, události, výjimky) podle metodiky `metodika/normalizace-2026.09.json`,
  2. IČO: doplnění nul a kontrola modulo 11; neplatné IČO -> výjimka. IČO, které platforma ještě
     nezná (není v core.subjekt), se ověří v kotvě (pvk.kotva, v pilotu ARES) – nic z kotvy se neukládá;
     IČO nenalezené v kotvě -> výjimka, strana toku zůstane neurčená,
  3. cizí měna: přepočet kurzem ČNB k datu uzavření, původní hodnota zůstává; bez kurzu příznak,
  4. zápis do core jen přes core.zapis_verzi() s klíči z přirozených klíčů (D-015): opakovaný běh
     nic nezdvojí. Každý zdrojový záznam založí tok, nebo se na něj naváže (tok_zdroj, doložená vazba).

Bitemporalita: valid_from = datum události ve světě (uveřejnění, uzavření, rozhodnutí), transaction
time (recorded_from) přiděluje databáze při zápisu. Dodatky, zrušení a zneplatnění jsou události,
nic se nepřepisuje.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg

from pvk.castka import Castka, DphRezim, Perioda, TypCastky
from pvk.config import KOREN
from pvk.core import klic_entity, zajisti_metodiku, zapis_entity
from pvk.ico import ico_platne, normalizuj_ico
from pvk.raw import kanonicky_json

LOG = logging.getLogger("pvk.normalizace")
SPOLECNY_TOK = (("vvz", "vvz_detail"),)
METODIKA = KOREN / "metodika" / "normalizace-2026.09.json"


# --- normalizovaný záznam -----------------------------------------------------------------------


@dataclass
class NCastka:
    klic: str  # přirozený klíč částky (unikátní v rámci zdroje)
    typ: str
    hodnota: Decimal
    mena: str
    dph_rezim: str
    perioda: str
    datum: date  # datum uzavření / rozhodnutí: platnost ve světě a datum kurzu
    stav_dat_k: date | None = None

    def over(self) -> Castka:
        """Typová kontrola přes pvk.castka (typ, měna, režim DPH, perioda jsou povinné)."""
        return Castka(self.hodnota, TypCastky(self.typ), self.mena, DphRezim(self.dph_rezim), Perioda(self.perioda))


@dataclass
class NUdalost:
    klic: str
    typ: str
    datum: date
    popis: str | None = None


@dataclass
class NTok:
    klic: str  # přirozený klíč toku v rámci zdroje (D-026: tok nikdy nespojuje zdroje)
    druh: str  # verejna_zakazka | smlouva | dotace
    valid_from: date
    platce: str | None = None  # IČO ve zdroji (před kontrolou)
    prijemce: str | None = None
    prijemce_vice: bool = False
    predmet: str | None = None
    duvod_platce: str | None = None  # proč zdroj plátce neuvádí
    duvod_prijemce: str | None = None


@dataclass
class NZaznam:
    raw_id: int
    zdroj: str
    id_ve_zdroji: str
    druh: str  # core.zdrojovy_zaznam.druh
    url: str
    valid_from: date
    toky: list[NTok] = field(default_factory=list)
    castky: list[tuple[str, NCastka]] = field(default_factory=list)  # (klíč toku, částka)
    udalosti: list[tuple[str, NUdalost]] = field(default_factory=list)
    vyjimky: list[tuple[str, str, str | None, str]] = field(default_factory=list)  # druh, pole, hodnota, popis
    ica: list[tuple[str, object]] = field(default_factory=list)  # (pole, hodnota IČO ve zdroji)


# --- IČO ------------------------------------------------------------------------------------------


def over_ico(hodnota: object) -> tuple[str | None, str | None]:
    """(IČO, None) pro platné IČO (doplněné nuly), (None, důvod) pro neplatné, (None, None) když chybí."""
    if hodnota is None or (isinstance(hodnota, str) and not hodnota.strip()):
        return None, None
    ico = normalizuj_ico(hodnota)
    if ico is None:
        return None, "ico_neplatny_format"
    if not ico_platne(ico):
        return None, "ico_neplatna_kontrolni_cislice"
    return ico, None


# --- běh normalizace ------------------------------------------------------------------------------


@dataclass
class Statistika:
    zaznamu: Counter = field(default_factory=Counter)
    toku: Counter = field(default_factory=Counter)
    castek: Counter = field(default_factory=Counter)
    castek_ve_zdroji: Counter = field(default_factory=Counter)  # částky nalezené ve zdroji (s typem i bez)
    ukonceno: Counter = field(default_factory=Counter)  # logicky ukončené entity (oprava bez mazání)
    castek_s_typem: Counter = field(default_factory=Counter)
    prepocet: Counter = field(default_factory=Counter)
    udalosti: Counter = field(default_factory=Counter)
    vyjimek: Counter = field(default_factory=Counter)
    ico_ve_zdroji: dict = field(default_factory=lambda: defaultdict(set))
    ico_neplatna: dict = field(default_factory=lambda: defaultdict(set))
    ico_nenalezena: dict = field(default_factory=lambda: defaultdict(set))
    poznamky: list[str] = field(default_factory=list)


def nacti_metodiku(conn: psycopg.Connection, cesta: Path = METODIKA) -> tuple[dict, str]:
    definice = json.loads(cesta.read_text(encoding="utf-8"))
    import hashlib

    md = cesta.with_suffix(".md")
    sha = hashlib.sha256(md.read_bytes()).hexdigest() if md.is_file() else None
    klic = zajisti_metodiku(conn, definice, sha)
    conn.commit()
    return definice, str(klic)


def _dejs(d: object) -> object:
    return json.loads(kanonicky_json(d))


def zapis_zaznamy(
    conn: psycopg.Connection,
    zaznamy: list[NZaznam],
    *,
    beh_id: int,
    metodika_id: str,
    kotva,
    kurzy,
    stat: Statistika,
    znama_ica: dict[str, str],
) -> None:
    """Zapíše normalizované záznamy jednoho zdroje do core (jedna transakce, každá entita nejvýš jednou)."""
    if not zaznamy:
        return

    # 1. IČO: kontrola, ověření neznámých IČO v kotvě (hromadně, bez ukládání údajů kotvy)
    zdroj_zaznamu = {z.raw_id: z.zdroj for z in zaznamy}
    platna: dict[tuple[int, str], str] = {}
    for z in zaznamy:
        for pole, hodnota in z.ica:
            ico, duvod = over_ico(hodnota)
            if hodnota not in (None, ""):
                stat.ico_ve_zdroji[z.zdroj].add(ico or str(hodnota).strip())
            if duvod:
                stat.ico_neplatna[z.zdroj].add(str(hodnota).strip())
                z.vyjimky.append((duvod, pole, str(hodnota)[:100], "IČO neprošlo kontrolou (8 číslic, modulo 11)"))
            elif ico:
                platna[(z.raw_id, pole)] = ico
    nezname = sorted({i for i in platna.values() if i not in znama_ica})
    if nezname:
        nalezene = kotva.subjekty_podle_ico(nezname)
        for ico in nezname:
            if nalezene.get(ico) is not None:
                znama_ica[ico] = str(klic_entity("subjekt", ico))
    nenalezena = {i for i in platna.values() if i not in znama_ica}
    for (raw_id, _pole), ico in platna.items():
        if ico in nenalezena:
            stat.ico_nenalezena[zdroj_zaznamu[raw_id]].add(ico)
    for z in zaznamy:
        for pole, _h in z.ica:
            ico = platna.get((z.raw_id, pole))
            if ico in nenalezena:
                z.vyjimky.append(("ico_nenalezeno_v_kotve", pole, ico, "IČO v kotvě (ARES) nenalezeno"))

    def subjekt(ico: str | None) -> str | None:
        return znama_ica.get(ico) if ico and ico not in nenalezena else None

    # 2. toky: sloučení podle klíče (tok zakládá první záznam, další se navazují)
    toky: dict[str, NTok] = {}
    zdroj_toku: dict[str, str] = {}
    for z in zaznamy:
        for t in z.toky:
            t.platce = normalizuj_ico(t.platce) if t.platce else None
            t.prijemce = normalizuj_ico(t.prijemce) if t.prijemce else None
            if t.klic not in toky:
                toky[t.klic] = t
                zdroj_toku[t.klic] = z.zdroj
                continue
            u = toky[t.klic]
            u.valid_from = min(u.valid_from, t.valid_from)
            u.platce = u.platce or t.platce
            u.predmet = u.predmet or t.predmet
            if t.prijemce and u.prijemce and t.prijemce != u.prijemce or t.prijemce_vice:
                u.prijemce_vice = True
            u.prijemce = u.prijemce or t.prijemce
            u.duvod_platce = u.duvod_platce or t.duvod_platce
            u.duvod_prijemce = u.duvod_prijemce or t.duvod_prijemce

    subjekty = {i for t in toky.values() for i in (t.platce, t.prijemce) if subjekt(i)}
    # nový subjekt jen s IČO (klíč z IČO); existující subjekt (i s jiným klíčem, např. z pilotu) se nemění
    zapis_entity(conn, "subjekt", [(ico, {"ico": ico}, date(1990, 1, 1), None) for ico in sorted(subjekty)
                                   if znama_ica[ico] == str(klic_entity("subjekt", ico))])

    polozky = []
    for t in toky.values():
        platce = subjekt(t.platce)
        prijemce = None if t.prijemce_vice else subjekt(t.prijemce)
        duvody = []
        if platce is None:
            duvody.append("plátce: " + (t.duvod_platce or ("IČO nenalezeno v kotvě" if t.platce else "zdroj IČO neuvádí")))
        if prijemce is None:
            duvody.append("příjemce: " + ("více příjemců (části)" if t.prijemce_vice else t.duvod_prijemce
                                          or ("IČO nenalezeno v kotvě" if t.prijemce else "zdroj IČO neuvádí")))
        data = {"druh": t.druh, "platce_subjekt_id": platce, "prijemce_subjekt_id": prijemce,
                "subjekt_neurcen_duvod": "; ".join(duvody) or None, "predmet": (t.predmet or "")[:500] or None}
        polozky.append((t.klic, data, t.valid_from, None))
        stat.toku[(zdroj_toku[t.klic], t.druh)] += 1
    zapis_entity(conn, "tok", polozky)

    # 3. zdrojové záznamy a vazby tok_zdroj (doložené: tok určuje identifikátor ve zdroji)
    zz, tz = [], []
    for z in zaznamy:
        zz.append((f"{z.zdroj}:{z.id_ve_zdroji}", {"raw_zaznam_id": z.raw_id, "zdroj": z.zdroj,
                                                     "id_ve_zdroji": z.id_ve_zdroji, "druh": z.druh, "url": z.url},
                   z.valid_from, None))
        for t in z.toky:
            tz.append((f"{t.klic}|{z.zdroj}:{z.id_ve_zdroji}", {
                "tok_id": str(klic_entity("tok", t.klic)),
                "zdrojovy_zaznam_id": str(klic_entity("zdrojovy_zaznam", f"{z.zdroj}:{z.id_ve_zdroji}")),
                "stav": "dolozena", "metoda": "identifikator_ve_zdroji", "skore": 1,
                "metodika_verze_id": metodika_id,
                "zduvodneni": "tok určuje identifikátor ve zdroji (" + t.klic.split(":", 1)[0] + ")",
            }, z.valid_from, None))
        stat.zaznamu[z.zdroj] += 1
    zapis_entity(conn, "zdrojovy_zaznam", zz)
    zapis_entity(conn, "tok_zdroj", tz)

    # 4. částky (typ, DPH, měna, perioda povinné; cizí měna kurzem ČNB k datu uzavření)
    cp, videne = [], set()
    for z in zaznamy:
        for tok_klic, c in z.castky:
            if c.klic in videne:
                continue
            videne.add(c.klic)
            c.over()
            data = {"tok_id": str(klic_entity("tok", tok_klic)),
                    "zdrojovy_zaznam_id": str(klic_entity("zdrojovy_zaznam", f"{z.zdroj}:{z.id_ve_zdroji}")),
                    "typ": c.typ, "hodnota": c.hodnota, "mena": c.mena, "dph_rezim": c.dph_rezim,
                    "perioda": c.perioda, "stav_dat_k": c.stav_dat_k, "prepocet": "neni_treba"}
            if c.mena != "CZK":
                kurz = kurzy.kurz(c.mena, c.datum) if kurzy is not None else None
                if kurz is None:
                    data["prepocet"] = "kurz_nedostupny"
                    z.vyjimky.append(("kurz_nedostupny", c.klic.rsplit(":", 1)[-1], f"{c.mena} {c.datum}",
                                      "kurz ČNB k datu uzavření není k dispozici, částka nepřepočtena"))
                else:
                    data.update(prepocet="kurz_cnb", kurz_cnb=kurz[0], kurz_datum=kurz[1],
                                hodnota_czk=(c.hodnota * kurz[0]).quantize(Decimal("0.01")))
            stat.prepocet[(z.zdroj, data["prepocet"])] += 1
            stat.castek[(z.zdroj, c.typ)] += 1
            stat.castek_s_typem[z.zdroj] += 1
            cp.append((c.klic, data, c.datum, None))
    zapis_entity(conn, "castka", cp)

    # 5. události (dodatek, zrušení, zneplatnění ... nic se nepřepisuje)
    up, videne = [], set()
    for z in zaznamy:
        for tok_klic, u in z.udalosti:
            if u.klic in videne:
                continue
            videne.add(u.klic)
            up.append((u.klic, {"tok_id": str(klic_entity("tok", tok_klic)) if tok_klic else None,
                                "zdrojovy_zaznam_id": str(klic_entity("zdrojovy_zaznam", f"{z.zdroj}:{z.id_ve_zdroji}")),
                                "typ": u.typ, "datum": u.datum, "popis": u.popis}, u.datum, None))
            stat.udalosti[(z.zdroj, u.typ)] += 1
    zapis_entity(conn, "udalost", up)

    # 6. výjimky (pouze INSERT, stejná výjimka téhož záznamu jen jednou)
    vy = [(beh_id, z.raw_id, z.zdroj, druh, pole, hodnota, popis)
          for z in zaznamy for druh, pole, hodnota, popis in z.vyjimky]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO core.normalizace_vyjimka (beh_id, raw_zaznam_id, zdroj, druh, pole, hodnota, popis) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (raw_zaznam_id, druh, pole) DO NOTHING",
            vy,
        )
    for _b, _r, zd, druh, *_x in vy:
        stat.vyjimek[(zd, druh)] += 1

    # 7. oprava bez mazání: entity dříve odvozené z týchž zdrojových záznamů, které dnešní normalizace
    #    nevytváří (např. tok celé zakázky, která je rozdělena na části), se logicky ukončí (D-044)
    ukonci_nahrazene(conn, beh_id, [klic_entity("zdrojovy_zaznam", f"{z.zdroj}:{z.id_ve_zdroji}") for z in zaznamy],
                     {"tok": {klic_entity("tok", k) for k, *_x in polozky},
                      "tok_zdroj": {klic_entity("tok_zdroj", k) for k, *_x in tz},
                      "castka": {klic_entity("castka", k) for k, *_x in cp},
                      "udalost": {klic_entity("udalost", k) for k, *_x in up}}, stat)


def ukonci_nahrazene(conn: psycopg.Connection, beh_id: int, zaznamy_id: list, nove: dict[str, set], stat) -> None:
    """Uzavře aktuální verze entit (vazby, částky, události, toky) odvozených z daných zdrojových záznamů,
    které v novém výsledku nejsou. Tok se ukončí, jen když na něj po opravě nevede žádná aktuální vazba."""
    if not zaznamy_id:
        return
    duvod = "oprava normalizace: entita nahrazena (např. tok celé zakázky toky jejích částí)"
    stare_tz = conn.execute(
        "SELECT tok_zdroj_id, tok_id FROM core.tok_zdroj WHERE recorded_to = 'infinity' AND zdrojovy_zaznam_id = ANY(%s)",
        (zaznamy_id,)).fetchall()
    ukoncit: list[tuple[str, object, list]] = []
    kandidati_toku = set()
    for r in stare_tz:
        if r["tok_zdroj_id"] not in nove["tok_zdroj"]:
            ukoncit.append(("tok_zdroj", r["tok_zdroj_id"], []))
            if r["tok_id"] not in nove["tok"]:
                kandidati_toku.add(r["tok_id"])
    for tabulka in ("castka", "udalost"):
        for r in conn.execute(f"SELECT {tabulka}_id AS id FROM core.{tabulka} WHERE recorded_to = 'infinity' "
                              "AND zdrojovy_zaznam_id = ANY(%s)", (zaznamy_id,)):
            if r["id"] not in nove[tabulka]:
                ukoncit.append((tabulka, r["id"], []))
    koncici_tz = {k for t, k, _n in ukoncit if t == "tok_zdroj"}
    for tok_id in kandidati_toku:
        zbyva = conn.execute("SELECT count(*) AS n FROM core.tok_zdroj WHERE recorded_to = 'infinity' AND tok_id = %s "
                             "AND tok_zdroj_id <> ALL(%s)", (tok_id, list(koncici_tz))).fetchone()["n"]
        if zbyva == 0:
            nahrada = sorted({str(r["tok_id"]) for r in conn.execute(
                "SELECT DISTINCT tok_id FROM core.tok_zdroj WHERE zdrojovy_zaznam_id IN (SELECT zdrojovy_zaznam_id "
                "FROM core.tok_zdroj WHERE tok_id = %s) AND recorded_to = 'infinity'", (tok_id,))} & {str(t) for t in nove["tok"]})
            ukoncit.append(("tok", tok_id, nahrada))
    with conn.cursor() as cur:
        cur.executemany("SELECT core.ukonci_entitu(%s::regclass, %s, %s, %s::uuid[], %s)",
                        [(f"core.{t}", k, duvod, n, beh_id) for t, k, n in ukoncit])
    for t, _k, _n in ukoncit:
        stat.ukonceno[t] += 1


def znama_ica(conn: psycopg.Connection) -> dict[str, str]:
    """IČO, která platforma už zná (core.subjekt) -> klíč subjektu."""
    return {r["ico"].strip(): str(r["subjekt_id"]) for r in conn.execute(
        "SELECT ico, subjekt_id FROM core.subjekt_aktualni WHERE valid_to = 'infinity'")}


def zahaj_beh(conn: psycopg.Connection, metodika_id: str, parametry: dict) -> int:
    row = conn.execute(
        "INSERT INTO core.normalizace_beh (metodika_verze_id, parametry) VALUES (%s, %s::jsonb) RETURNING id",
        (metodika_id, json.dumps(_dejs(parametry), ensure_ascii=False)),
    ).fetchone()
    conn.commit()
    return row["id"]


def normalizuj(conn: psycopg.Connection, zdroje: Iterable[str], kotva, kurzy, stat: Statistika | None = None,
               vcetne_vyvojovych: bool = True) -> Statistika:
    """Normalizuje všechny záznamy raw vybraných zdrojů (nejnovější verze každého ID ve zdroji)."""
    from pvk.normalizace import zdroje as adaptery

    stat = stat or Statistika()
    definice, metodika_id = nacti_metodiku(conn)
    beh_id = zahaj_beh(conn, metodika_id, {"zdroje": list(zdroje), "metodika": definice["kod"]})
    znama = znama_ica(conn)
    # zdroje se společným klíčem toku (souhrn a detail týchž formulářů VVZ) se zapisují společně, aby každý
    # tok vznikl v běhu jednou verzí (jinak by se verze toku při každém běhu střídaly)
    skupiny: list[tuple[str, ...]] = []
    for zdroj in zdroje:
        skupina = tuple(x for x in next((s for s in SPOLECNY_TOK if zdroj in s), (zdroj,)) if x in zdroje)
        if skupina not in skupiny:
            skupiny.append(skupina)
    for skupina in skupiny:
        zaznamy = []
        for zdroj in skupina:
            zaznamy += adaptery.ADAPTERY[zdroj](conn, definice["parametry"], stat, vcetne_vyvojovych)
        LOG.info("normalizace %s: %d záznamů", "+".join(skupina), len(zaznamy))
        zapis_zaznamy(conn, zaznamy, beh_id=beh_id, metodika_id=metodika_id, kotva=kotva, kurzy=kurzy,
                      stat=stat, znama_ica=znama)
        conn.commit()
    if kurzy is not None and kurzy.chyby:
        stat.poznamky += kurzy.chyby
    return stat
