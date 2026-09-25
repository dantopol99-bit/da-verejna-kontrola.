"""IČO: normalizace a kontrola (8 číslic, kontrolní číslice modulo 11)."""

from __future__ import annotations

import re

_NECISLICE = re.compile(r"\D")


def ico_platne(ico: str | None) -> bool:
    if ico is None or not re.fullmatch(r"\d{8}", ico):
        return False
    soucet = sum(int(c) * v for c, v in zip(ico[:7], range(8, 1, -1), strict=True))
    return (11 - soucet % 11) % 10 == int(ico[7])


def normalizuj_ico(hodnota: object) -> str | None:
    """Vrátí IČO jako 8 číslic (doplní úvodní nuly), nebo None, pokud hodnota IČO být nemůže.

    Nekontroluje kontrolní číslici – to dělá ico_platne(). Zdroje uvádějí IČO různě:
    '00255513', '255513', 'CZ00255513' (DIČ), 255513 (číslo v XLSX), '002 55 513'.
    """
    if hodnota is None:
        return None
    if isinstance(hodnota, float):
        if hodnota != hodnota or hodnota <= 0:  # NaN
            return None
        hodnota = int(hodnota)
    text = str(hodnota).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+\.0+", text):  # číslo z tabulky ve tvaru "255513.0"
        text = text.split(".", 1)[0]
    if text.upper().startswith("CZ"):
        text = text[2:]
    cislice = _NECISLICE.sub("", text)
    if not cislice or len(cislice) > 8 or int(cislice) == 0:
        return None
    # nepřijímáme text, kde číslice tvoří jen malou část (např. adresa)
    if len(cislice) < len(text.replace(" ", "")) - 2:
        return None
    return cislice.zfill(8)
