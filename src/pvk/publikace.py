"""Publikační brána: podmínky, za kterých se výstup NEPUBLIKUJE.

Podmínky nepublikování (každá má kód porušení):
  INDIKATOR_BEZ_OBDOBI, INDIKATOR_BEZ_POCTU_PRIPADU, INDIKATOR_BEZ_VERZE_METODIKY
  INDIKATOR_POD_MINIMALNIM_ZAKLADEM
  CASTKA_BEZ_TYPU (a bez měny / režimu DPH / periody)
  SOUHRN_RUZNYCH_TYPU
  SOUHRN_BEZ_PODILU_HEURISTIKY
  HODNOTICI_SLOVA  (podezřelý, rizikový dodavatel, propojen s, napojen na – ve všech tvarech)
  PROFIL_FYZICKE_OSOBY  (fyzické osoby se nikdy nezobrazují jako samostatné profily)

Brána se spouští jako `python -m pvk.publikace` (make gate / make pilot) a v testech
(tests/test_publikacni_podminky.py); jakékoli porušení ve výstupech shodí build.
Stejná pravidla drží i databáze (NOT NULL, core.soucet, pohledy ind.*_k_publikaci).
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pvk.config import KOREN

# Vzory se hledají v textu malými písmeny; tvary s diakritikou i bez ní. Podstatná jména
# "napojení na" / "propojení s" (technické napojení na kanalizaci apod.) nejsou hodnotící, proto
# jsou vyloučena tvarem s "í"; text bez diakritiky ("napojeni na") se posuzuje přísně jako hodnotící.
# Pozor: stejné vzory jsou v SQL funkci ind.obsahuje_hodnotici_slova (migrace 0004).
HODNOTICI_VZORY: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpodez[řr]"), "podezřelý / podezření"),
    (re.compile(r"\brizikov\w*\s+dodavatel"), "rizikový dodavatel"),
    (re.compile(r"\bpropojen(?!í)\w*\s+se?\b"), "propojen s"),
    (re.compile(r"\bnapojen(?!í)\w*\s+na\b"), "napojen na"),
)

# Kde leží výstupy, které se kontrolují (relativně ke kořeni repozitáře).
VYSTUPNI_ADRESARE = ("vystupy",)
VYSTUPNI_SOUBORY = ("docs/pilot_report.md", "docs/pilot_vyjimky.csv", "docs/pilot_vyjimky_kategorie.csv")
ADRESAR_METODIK = "metodika"


@dataclass(frozen=True)
class Poruseni:
    kod: str
    popis: str
    kde: str = ""

    def __str__(self) -> str:
        return f"[{self.kod}] {self.kde}: {self.popis}" if self.kde else f"[{self.kod}] {self.popis}"


def normalizuj_text(text: str) -> str:
    """Malá písmena v normalizované podobě NFC (diakritika zůstává)."""
    return unicodedata.normalize("NFC", text).lower()


def najdi_hodnotici_slova(text: str | None) -> list[str]:
    if not text:
        return []
    norm = normalizuj_text(text)
    return [nazev for vzor, nazev in HODNOTICI_VZORY if vzor.search(norm)]


def over_text(text: str | None, kde: str = "") -> list[Poruseni]:
    return [
        Poruseni("HODNOTICI_SLOVA", f"výstupní text obsahuje hodnotící výraz „{nazev}“", kde)
        for nazev in najdi_hodnotici_slova(text)
    ]


def _chybi(hodnota: object) -> bool:
    return hodnota is None or (isinstance(hodnota, str) and not hodnota.strip())


def over_indikator(v: Mapping, metodika: Mapping | None, kde: str = "") -> list[Poruseni]:
    """v: výstup indikátoru; metodika: parametry verze metodiky (min_pocet_pripadu, min_zaklad)."""
    p: list[Poruseni] = []
    if _chybi(v.get("obdobi_od")) or _chybi(v.get("obdobi_do")):
        p.append(Poruseni("INDIKATOR_BEZ_OBDOBI", "indikátor nemá období (od–do)", kde))
    if v.get("pocet_pripadu") is None:
        p.append(Poruseni("INDIKATOR_BEZ_POCTU_PRIPADU", "indikátor nemá počet případů", kde))
    if _chybi(v.get("metodika_verze")):
        p.append(Poruseni("INDIKATOR_BEZ_VERZE_METODIKY", "indikátor nemá verzi metodiky", kde))
    elif metodika is None:
        p.append(
            Poruseni(
                "INDIKATOR_BEZ_VERZE_METODIKY",
                f"verze metodiky {v.get('metodika_verze')!r} není v registru metodik",
                kde,
            )
        )
    if metodika is not None and v.get("pocet_pripadu") is not None:
        minimum = metodika.get("min_pocet_pripadu")
        if minimum is None:
            p.append(
                Poruseni("INDIKATOR_POD_MINIMALNIM_ZAKLADEM", "metodika neurčuje minimální základ", kde)
            )
        elif int(v["pocet_pripadu"]) < int(minimum):
            p.append(
                Poruseni(
                    "INDIKATOR_POD_MINIMALNIM_ZAKLADEM",
                    f"počet případů {v['pocet_pripadu']} < minimum {minimum}",
                    kde,
                )
            )
        min_zaklad = metodika.get("min_zaklad")
        if min_zaklad is not None and v.get("zaklad") is not None and float(v["zaklad"]) < float(min_zaklad):
            p.append(
                Poruseni(
                    "INDIKATOR_POD_MINIMALNIM_ZAKLADEM", f"základ {v['zaklad']} < minimum {min_zaklad}", kde
                )
            )
    p += over_text(v.get("text"), kde)
    return p


def over_castku(c: Mapping, kde: str = "") -> list[Poruseni]:
    p: list[Poruseni] = []
    if _chybi(c.get("typ")):
        p.append(Poruseni("CASTKA_BEZ_TYPU", "částka nemá typ", kde))
    for pole in ("mena", "dph_rezim", "perioda"):
        if _chybi(c.get(pole)):
            p.append(Poruseni("CASTKA_BEZ_TYPU", f"částka nemá {pole}", kde))
    return p


def over_souhrn(s: Mapping, kde: str = "") -> list[Poruseni]:
    """s: souhrn se seznamem sečtených částek (castky) nebo s popisem druhu (typ, mena, ...)."""
    p: list[Poruseni] = []
    castky = s.get("castky")
    if castky is not None:
        druhy = set()
        for i, c in enumerate(castky):
            p += over_castku(c, f"{kde} castky[{i}]")
            druhy.add((c.get("typ"), c.get("mena"), c.get("dph_rezim"), c.get("perioda")))
        if len(druhy) > 1:
            p.append(
                Poruseni(
                    "SOUHRN_RUZNYCH_TYPU",
                    f"souhrn sčítá částky různých druhů: {sorted(map(str, druhy))}",
                    kde,
                )
            )
    else:
        p += over_castku(s, kde)
    podil = s.get("podil_heuristicke_deduplikace")
    if podil is None:
        p.append(
            Poruseni(
                "SOUHRN_BEZ_PODILU_HEURISTIKY",
                "souhrn neuvádí podíl objemu stojící na heuristické deduplikaci",
                kde,
            )
        )
    elif not 0 <= float(podil) <= 1:
        p.append(Poruseni("SOUHRN_BEZ_PODILU_HEURISTIKY", f"podíl mimo interval 0–1: {podil}", kde))
    p += over_text(s.get("text"), kde)
    return p


def over_profil(profil: Mapping, kde: str = "") -> list[Poruseni]:
    p: list[Poruseni] = []
    if profil.get("je_fyzicka_osoba") is not False:
        # neznámý typ osoby se chová jako fyzická osoba: profil se nepublikuje
        p.append(
            Poruseni(
                "PROFIL_FYZICKE_OSOBY",
                "profil subjektu lze publikovat jen u právnické osoby (je_fyzicka_osoba musí být false)",
                kde,
            )
        )
    p += over_text(profil.get("text"), kde)
    return p


def nacti_metodiky(koren: Path = KOREN) -> dict[str, dict]:
    """Registr verzí metodiky: metodika/<kod>.json -> parametry."""
    metodiky: dict[str, dict] = {}
    for soubor in sorted((koren / ADRESAR_METODIK).glob("*.json")):
        data = json.loads(soubor.read_text(encoding="utf-8"))
        metodiky[data["kod"]] = data.get("parametry", {})
    return metodiky


def over_vystup(vystup: Mapping, metodiky: Mapping[str, Mapping], kde: str) -> list[Poruseni]:
    druh = vystup.get("druh")
    if druh == "indikator":
        return over_indikator(vystup, metodiky.get(str(vystup.get("metodika_verze"))), kde)
    if druh == "souhrn":
        return over_souhrn(vystup, kde)
    if druh == "castka":
        return over_castku(vystup, kde)
    if druh == "profil":
        return over_profil(vystup, kde)
    if druh == "text":
        return over_text(vystup.get("text"), kde)
    return [Poruseni("NEZNAMY_VYSTUP", f"výstup bez známého druhu: {druh!r}", kde)]


def _vystupy_v_json(data: object) -> Iterable[Mapping]:
    if isinstance(data, list):
        for polozka in data:
            yield from _vystupy_v_json(polozka)
    elif isinstance(data, Mapping):
        yield data


def over_vystupy(koren: Path = KOREN) -> list[Poruseni]:
    """Zkontroluje všechny publikované výstupy v repozitáři (adresář vystupy/ a report pilotu)."""
    metodiky = nacti_metodiky(koren)
    poruseni: list[Poruseni] = []
    soubory: list[Path] = [koren / s for s in VYSTUPNI_SOUBORY if (koren / s).is_file()]
    for adresar in VYSTUPNI_ADRESARE:
        if (koren / adresar).is_dir():
            soubory += sorted(p for p in (koren / adresar).rglob("*") if p.is_file())
    for soubor in soubory:
        kde = str(soubor.relative_to(koren))
        if soubor.suffix == ".json":
            try:
                data = json.loads(soubor.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                poruseni.append(Poruseni("NECITELNY_VYSTUP", f"neplatný JSON: {e}", kde))
                continue
            for i, vystup in enumerate(_vystupy_v_json(data)):
                poruseni += over_vystup(vystup, metodiky, f"{kde}#{i}")
        elif soubor.suffix in {".md", ".txt", ".html", ".csv"}:
            poruseni += over_text(soubor.read_text(encoding="utf-8"), kde)
    return poruseni


def main(argv: list[str] | None = None) -> int:
    koren = Path(argv[0]) if argv else KOREN
    poruseni = over_vystupy(koren)
    if poruseni:
        print("Publikační brána: výstupy NELZE publikovat:", file=sys.stderr)
        for p in poruseni:
            print(f"  {p}", file=sys.stderr)
        return 1
    print("Publikační brána: bez porušení.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
