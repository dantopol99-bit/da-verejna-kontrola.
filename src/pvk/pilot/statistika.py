"""Podíly s 95% intervalem spolehlivosti (Wilsonův interval – funguje i u malých vzorků a podílů u 0 či 1)."""

from __future__ import annotations

import math
from dataclasses import dataclass

Z95 = 1.959963984540054


@dataclass(frozen=True)
class Podil:
    citatel: int
    jmenovatel: int

    @property
    def hodnota(self) -> float | None:
        return self.citatel / self.jmenovatel if self.jmenovatel else None

    @property
    def interval(self) -> tuple[float, float] | None:
        n = self.jmenovatel
        if not n:
            return None
        p = self.citatel / n
        jm = 1 + Z95**2 / n
        stred = (p + Z95**2 / (2 * n)) / jm
        polovina = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n**2)) / jm
        dolni = 0.0 if self.citatel == 0 else max(0.0, stred - polovina)
        horni = 1.0 if self.citatel == n else min(1.0, stred + polovina)
        return dolni, horni

    def text(self) -> str:
        if not self.jmenovatel:
            return "neměřeno (0 případů)"
        dolni, horni = self.interval
        return (
            f"{procenta(self.hodnota)} ({self.citatel}/{self.jmenovatel}; 95% IS {procenta(dolni)}–{procenta(horni)})"
        )

    def jako_dict(self) -> dict:
        i = self.interval
        return {
            "citatel": self.citatel,
            "jmenovatel": self.jmenovatel,
            "podil": self.hodnota,
            "is95": list(i) if i else None,
        }


def procenta(x: float | None) -> str:
    if x is None:
        return "–"
    return f"{100 * x:.1f} %".replace(".", ",")
