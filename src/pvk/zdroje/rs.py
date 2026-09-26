"""Společný model záznamu registru smluv (nezávislý na tom, zda pochází z oficiálních dumpů,
nebo ze zrcadla)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pvk.ico import ico_platne, normalizuj_ico


@dataclass
class StranaRS:
    nazev: str | None
    ico: str | None  # normalizované 8místné IČO (nebo None)
    ico_ve_zdroji: str | None = None
    datova_schranka: str | None = None
    platce: bool | None = None
    prijemce: bool | None = None

    @property
    def ico_platne(self) -> bool:
        return ico_platne(self.ico)


@dataclass
class PrilohaRS:
    nazev: str
    sha256: str | None  # hash z metadat registru
    url_original: str | None  # soubor na smlouvy.gov.cz
    url_stazeni: str | None  # odkud jsme soubor skutečně stáhli (originál nebo zrcadlo)


@dataclass
class ZaznamRS:
    id_verze: str
    id_smlouvy: str | None
    odkaz: str
    cas_zverejneni: datetime | None
    subjekt: StranaRS | None
    smluvni_strany: list[StranaRS]
    predmet: str | None
    datum_uzavreni: date | None
    cislo_smlouvy: str | None
    hodnota_bez_dph: Decimal | None
    hodnota_vcetne_dph: Decimal | None
    cizi_mena_hodnota: Decimal | None
    cizi_mena: str | None
    duvod_neuvedeni_ceny: str | None
    navazany_zaznam: str | None
    prilohy: list[PrilohaRS]
    platny: bool
    zdroj: str
    poznamky: list[str] = field(default_factory=list)

    @property
    def ma_castku(self) -> bool:
        return any(v is not None for v in (self.hodnota_bez_dph, self.hodnota_vcetne_dph, self.cizi_mena_hodnota))

    def ica_stran(self) -> list[str]:
        return [s.ico for s in self.smluvni_strany if s.ico]

    def jako_dict(self) -> dict:
        """Záznam pro raw.zaznam.obsah. Názvy stran bez IČO se vynechávají (minimalizace osobních údajů)."""
        d = asdict(self)
        for strana in [d["subjekt"], *d["smluvni_strany"]]:
            if strana and not strana.get("ico"):
                strana["nazev"] = None
                strana["datova_schranka"] = None
        return d


def odkaz_rs(id_verze: str | int) -> str:
    return f"https://smlouvy.gov.cz/smlouva/{id_verze}"


def na_decimal(text: str | None) -> Decimal | None:
    """'20 068 576 Kč' / '20068576.50' / '1 234,5' -> Decimal."""
    if text is None:
        return None
    t = str(text).replace(" ", " ").replace("Kč", "").replace("CZK", "").strip()
    t = t.replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return Decimal(t) if t else None
    except InvalidOperation:
        return None


def strana(nazev: str | None, ico: str | None, **kw) -> StranaRS:
    return StranaRS(nazev=nazev, ico=normalizuj_ico(ico), ico_ve_zdroji=ico, **kw)
