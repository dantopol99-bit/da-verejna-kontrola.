"""Extrakce textu z příloh smluv a detekce znečitelnění.

* PDF: textová vrstva přes `pdftotext` (poppler), stránky bez textu se OCRují (`pdftoppm` +
  `tesseract -l ces+eng`), nejvýše `max_stran_ocr` stran na dokument.
* Znečitelnění: (a) vyplněné tmavé obdélníky ve vektorovém PDF (pdfplumber), (b) souvislé černé
  bloky ve vykreslených stranách skenu, (c) textové značky (XXXXX, █, „anonymizováno“...) –
  ty řeší pvk.text.analyza.
* DOCX/ODT: text z XML uvnitř ZIPu; RTF: odstranění řídicích slov; obrázky: OCR.
* Ostatní formáty (DOC, XLS...) se označí jako nepodporované – nevymýšlíme obsah.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

MIN_ZNAKU_NA_STRANU = 40
MAX_STRAN_TEXT = 150


@dataclass
class TextPrilohy:
    text: str
    format: str
    stran: int | None = None
    ocr_stran: int = 0
    metoda: str = "textova_vrstva"
    cerne_obdelniky: int = 0
    cerne_bloky_sken: int = 0
    orezano: bool = False
    chyba: str | None = None
    poznamky: list[str] = field(default_factory=list)

    @property
    def citelny(self) -> bool:
        return len(self.text.strip()) >= MIN_ZNAKU_NA_STRANU


def rozpoznej_format(obsah: bytes, nazev: str = "") -> str:
    if obsah.startswith(b"%PDF") or b"%PDF-" in obsah[:1024]:
        return "pdf"
    if obsah.startswith(b"PK"):
        try:
            with zipfile.ZipFile(_bytesio(obsah)) as z:
                jmena = set(z.namelist())
        except zipfile.BadZipFile:
            return "jiny"
        if "word/document.xml" in jmena:
            return "docx"
        if "content.xml" in jmena:
            return "odt"
        if any(j.startswith("xl/") for j in jmena):
            return "xlsx"
        return "zip"
    if obsah.startswith(b"{\\rtf"):
        return "rtf"
    if obsah.startswith((b"\x89PNG", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*")):
        return "obrazek"
    if obsah.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole"  # DOC/XLS
    if nazev.lower().endswith((".txt", ".csv")):
        return "text"
    return "jiny"


def _bytesio(obsah: bytes):
    import io

    return io.BytesIO(obsah)


def _spust(prikaz: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(prikaz, capture_output=True, timeout=timeout, check=False)


def ocr_dostupne() -> bool:
    return shutil.which("tesseract") is not None and shutil.which("pdftoppm") is not None


def cerne_bloky(obrazek: Image.Image) -> int:
    """Počet souvislých, téměř plně černých obdélníků velikosti řádku textu (typické začernění).

    Postup: obraz se zmenší na šířku 600 px, tmavé pixely (< 60) tvoří masku; v každém řádku se
    najdou úseky tmavých pixelů délky >= 25 px; úseky překrývající se v sousedních řádcích se spojí.
    Blok = výška 5–45 px, šířka 25 px až 90 % šířky strany, zaplnění >= 0,85.
    """
    sirka = 600
    if obrazek.width == 0:
        return 0
    vyska = max(1, round(obrazek.height * sirka / obrazek.width))
    maska = np.asarray(obrazek.convert("L").resize((sirka, vyska))) < 60
    useky_rady: list[list[tuple[int, int]]] = []
    for radek in maska:
        useky = []
        hrany = np.flatnonzero(np.diff(np.concatenate(([0], radek.view(np.int8), [0]))))
        for zac, kon in zip(hrany[::2], hrany[1::2], strict=True):
            if kon - zac >= 25:
                useky.append((int(zac), int(kon)))
        useky_rady.append(useky)
    # spojování úseků do bloků přes sousední řádky
    bloky: list[dict] = []
    otevrene: list[dict] = []
    for y, useky in enumerate(useky_rady):
        nove = []
        for zac, kon in useky:
            cil = None
            for b in otevrene:
                prekryv = min(kon, b["x1"]) - max(zac, b["x0"])
                if prekryv >= 0.8 * min(kon - zac, b["x1"] - b["x0"]):
                    cil = b
                    break
            if cil is None:
                cil = {"x0": zac, "x1": kon, "y0": y, "y1": y, "plocha": 0}
                bloky.append(cil)
            cil["x0"], cil["x1"] = min(cil["x0"], zac), max(cil["x1"], kon)
            cil["y1"] = y
            cil["plocha"] += kon - zac
            nove.append(cil)
        otevrene = nove
    pocet = 0
    for b in bloky:
        w, h = b["x1"] - b["x0"], b["y1"] - b["y0"] + 1
        if 5 <= h <= 45 and 25 <= w <= 0.9 * sirka and b["plocha"] / (w * h) >= 0.85:
            pocet += 1
    return pocet


def _vektorove_cerne_obdelniky(cesta: Path, max_stran: int = 40) -> int:
    try:
        import pdfplumber
    except ImportError:
        return 0
    pocet = 0
    try:
        with pdfplumber.open(cesta) as pdf:
            for strana in pdf.pages[:max_stran]:
                for r in strana.rects:
                    barva = r.get("non_stroking_color")
                    if not r.get("fill") or barva is None:
                        continue
                    hodnoty = barva if isinstance(barva, (list, tuple)) else [barva]
                    try:
                        hodnoty = [float(h) for h in hodnoty]
                    except (TypeError, ValueError):
                        continue
                    tmava = (
                        (len(hodnoty) == 1 and hodnoty[0] <= 0.15)
                        or (len(hodnoty) == 3 and max(hodnoty) <= 0.15)
                        or (len(hodnoty) == 4 and hodnoty[3] >= 0.85)
                    )
                    sirka, vyska = float(r["width"]), float(r["height"])
                    if tmava and 15 <= sirka <= 0.9 * float(strana.width) and 5 <= vyska <= 40:
                        pocet += 1
    except Exception:  # poškozené PDF: znečitelnění se pak posuzuje jen z textu
        return pocet
    return pocet


def _ocr_obrazku(cesta_png: Path) -> str:
    vysledek = _spust(["tesseract", str(cesta_png), "stdout", "-l", "ces+eng", "--psm", "3"], timeout=240)
    return vysledek.stdout.decode("utf-8", "replace")


def extrahuj_pdf(cesta: Path, max_stran_ocr: int = 12) -> TextPrilohy:
    vysledek = _spust(["pdftotext", "-layout", "-l", str(MAX_STRAN_TEXT), str(cesta), "-"], timeout=300)
    if vysledek.returncode != 0:
        return TextPrilohy("", "pdf", metoda="chyba", chyba=vysledek.stderr.decode("utf-8", "replace")[:300])
    strany = vysledek.stdout.decode("utf-8", "replace").split("\f")
    if strany and not strany[-1].strip():
        strany = strany[:-1]
    info = _spust(["pdfinfo", str(cesta)], timeout=60).stdout.decode("utf-8", "replace")
    m = re.search(r"^Pages:\s+(\d+)", info, re.M)
    celkem_stran = int(m.group(1)) if m else len(strany)
    tp = TextPrilohy("", "pdf", stran=celkem_stran, orezano=celkem_stran > MAX_STRAN_TEXT)
    tp.cerne_obdelniky = _vektorove_cerne_obdelniky(cesta)
    prazdne = [i for i, s in enumerate(strany) if len(s.strip()) < MIN_ZNAKU_NA_STRANU]
    if prazdne and ocr_dostupne():
        with tempfile.TemporaryDirectory() as tmp:
            for i in prazdne[:max_stran_ocr]:
                predpona = Path(tmp) / f"s{i + 1}"
                _spust(["pdftoppm", "-r", "200", "-gray", "-png", "-f", str(i + 1), "-l", str(i + 1),
                        str(cesta), str(predpona)], timeout=180)
                obrazky = sorted(Path(tmp).glob(f"s{i + 1}*.png"))
                if not obrazky:
                    continue
                strany[i] = _ocr_obrazku(obrazky[0])
                with Image.open(obrazky[0]) as img:
                    tp.cerne_bloky_sken += cerne_bloky(img)
                tp.ocr_stran += 1
        if len(prazdne) > max_stran_ocr:
            tp.orezano = True
            tp.poznamky.append(f"OCR jen prvních {max_stran_ocr} z {len(prazdne)} stran bez textu")
    elif prazdne:
        tp.poznamky.append("strany bez textové vrstvy, OCR není k dispozici")
    tp.text = "\n\f".join(strany)
    if tp.ocr_stran == 0:
        tp.metoda = "textova_vrstva"
    elif tp.ocr_stran >= len(strany):
        tp.metoda = "ocr"
    else:
        tp.metoda = "kombinace"
    return tp


def _xml_text(xml: str) -> str:
    xml = re.sub(r"</(w:p|text:p|text:h)>", "\n", xml)
    xml = re.sub(r"<(w:tab|text:tab)[^>]*/>", "\t", xml)
    return re.sub(r"<[^>]+>", "", xml)


def extrahuj(cesta: Path, nazev: str = "", max_stran_ocr: int = 12) -> TextPrilohy:
    obsah = cesta.read_bytes()
    fmt = rozpoznej_format(obsah, nazev)
    try:
        if fmt == "pdf":
            return extrahuj_pdf(cesta, max_stran_ocr)
        if fmt in ("docx", "odt"):
            with zipfile.ZipFile(cesta) as z:
                xml = z.read("word/document.xml" if fmt == "docx" else "content.xml").decode("utf-8", "replace")
            from html import unescape

            return TextPrilohy(unescape(_xml_text(xml)), fmt, metoda="textova_vrstva")
        if fmt == "rtf":
            text = obsah.decode("cp1250", "replace")
            text = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1250", "replace"), text)
            text = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", text)
            return TextPrilohy(text, fmt, metoda="textova_vrstva")
        if fmt == "text":
            return TextPrilohy(obsah.decode("utf-8", "replace"), fmt, metoda="textova_vrstva")
        if fmt == "obrazek" and ocr_dostupne():
            with Image.open(cesta) as img:
                bloky = cerne_bloky(img)
            return TextPrilohy(_ocr_obrazku(cesta), fmt, stran=1, ocr_stran=1, metoda="ocr", cerne_bloky_sken=bloky)
    except (subprocess.TimeoutExpired, zipfile.BadZipFile, KeyError, OSError) as e:
        return TextPrilohy("", fmt, metoda="chyba", chyba=f"{type(e).__name__}: {e}"[:300])
    return TextPrilohy("", fmt, metoda="nepodporovano")
