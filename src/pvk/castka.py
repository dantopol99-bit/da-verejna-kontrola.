"""Typovaná částka. Sčítání napříč typy je technicky znemožněno.

Částka nese vždy typ, měnu, režim DPH a periodu. Sčítat lze jen částky se shodou ve všech čtyřech;
jinak NesouhlasneCastky. Neexistuje sčítání s čísly (ani s 0), takže vestavěné sum() bez výchozí
typované nuly selže – součet se dělá přes secti(). Totéž platí v databázi (core.soucet, chyba PV003).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class TypCastky(StrEnum):
    PREDPOKLADANA = "predpokladana"
    VYSOUTEZENA = "vysoutezena"
    SMLUVNI = "smluvni"
    ZMENA_DODATKEM = "zmena_dodatkem"
    DOTACE_PRIZNANA = "dotace_priznana"
    DOTACE_CERPANA = "dotace_cerpana"
    VRATKA = "vratka"


class DphRezim(StrEnum):
    BEZ_DPH = "bez_dph"
    VCETNE_DPH = "vcetne_dph"
    MIMO_DPH = "mimo_dph"
    NEURCENO = "neurceno"


class Perioda(StrEnum):
    CELKEM = "celkem"
    ROCNI = "rocni"
    MESICNI = "mesicni"
    JEDNOTKOVA = "jednotkova"
    NEURCENA = "neurcena"


class NesouhlasneCastky(TypeError):
    """Pokus sečíst částky různého typu, měny, režimu DPH nebo periody."""


class NeuplnaCastka(ValueError):
    """Částka bez typu, měny, režimu DPH nebo periody."""


@dataclass(frozen=True, slots=True)
class Castka:
    hodnota: Decimal
    typ: TypCastky
    mena: str
    dph_rezim: DphRezim
    perioda: Perioda
    zdroj: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.typ is None or self.dph_rezim is None or self.perioda is None or not self.mena:
            raise NeuplnaCastka("částka musí mít typ, měnu, režim DPH a periodu")
        object.__setattr__(self, "typ", TypCastky(self.typ))
        object.__setattr__(self, "dph_rezim", DphRezim(self.dph_rezim))
        object.__setattr__(self, "perioda", Perioda(self.perioda))
        if not (len(self.mena) == 3 and self.mena.isalpha() and self.mena.isupper()):
            raise NeuplnaCastka(f"měna musí být kód ISO 4217, ne {self.mena!r}")
        if not isinstance(self.hodnota, Decimal):
            object.__setattr__(self, "hodnota", Decimal(str(self.hodnota)))

    @property
    def druh(self) -> tuple[TypCastky, str, DphRezim, Perioda]:
        """Vše, co musí souhlasit, aby šlo částky sečíst."""
        return (self.typ, self.mena, self.dph_rezim, self.perioda)

    def __add__(self, other: object) -> Castka:
        if not isinstance(other, Castka):
            raise NesouhlasneCastky(
                f"k částce lze přičíst jen částku stejného druhu, ne {type(other).__name__}"
            )
        if other.druh != self.druh:
            raise NesouhlasneCastky(f"sčítání částek různých druhů není povoleno: {self.druh} + {other.druh}")
        return Castka(self.hodnota + other.hodnota, self.typ, self.mena, self.dph_rezim, self.perioda)

    def __radd__(self, other: object) -> Castka:
        # sum([...]) začíná nulou: tu odmítáme, aby nevznikl netypovaný součet
        raise NesouhlasneCastky("částky se sčítají funkcí secti(), ne sum() nad čísly")

    @classmethod
    def nula(cls, typ: TypCastky, mena: str, dph_rezim: DphRezim, perioda: Perioda) -> Castka:
        return cls(Decimal("0"), typ, mena, dph_rezim, perioda)


def secti(castky: Iterable[Castka]) -> Castka:
    """Součet částek jednoho druhu. Prázdný vstup nebo mix druhů -> výjimka."""
    vysledek: Castka | None = None
    for c in castky:
        if not isinstance(c, Castka):
            raise NesouhlasneCastky(f"secti() přijímá jen Castka, ne {type(c).__name__}")
        vysledek = c if vysledek is None else vysledek + c
    if vysledek is None:
        raise ValueError("secti(): prázdný seznam částek nemá typ")
    return vysledek
