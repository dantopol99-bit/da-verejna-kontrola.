"""Porovnání názvů subjektů (zdroj × ARES) – normalizace právní formy, diakritiky a interpunkce."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_PRAVNI_FORMY = [
    "spol s r o", "s r o", "sro", "a s", "as", "v o s", "k s", "z s", "o p s", "z u", "se", "s p",
    "druzstvo", "p o", "o s", "v v i", "statni podnik", "prispevkova organizace", "zapsany spolek",
    "zapsany ustav", "obecne prospesna spolecnost", "spolecnost s rucenim omezenym", "akciova spolecnost",
    "z s p o", "gmbh", "ltd", "llc", "inc", "b v", "kft", "sp z o o",
]


def normalizuj_nazev(nazev: str | None) -> str:
    if not nazev:
        return ""
    t = unicodedata.normalize("NFKD", nazev)
    t = "".join(z for z in t if not unicodedata.combining(z)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    zmena = True
    while zmena:
        zmena = False
        for forma in _PRAVNI_FORMY:
            if t.endswith(" " + forma) or t == forma:
                t = t[: -len(forma)].strip()
                zmena = True
    return re.sub(r"\s+", " ", t)


def podobnost(a: str | None, b: str | None) -> float:
    """0–1: maximum z poměru SequenceMatcher a Jaccardovy shody slov (po normalizaci)."""
    na, nb = normalizuj_nazev(a), normalizuj_nazev(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    pomer = SequenceMatcher(None, na, nb).ratio()
    sa, sb = set(na.split()), set(nb.split())
    jaccard = len(sa & sb) / len(sa | sb)
    return max(pomer, jaccard)
