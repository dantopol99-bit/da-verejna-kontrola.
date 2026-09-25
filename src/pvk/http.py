"""Stahování ze zdrojů s evidencí původu.

Každý pokus o stažení (i neúspěšný) se zapíše do raw.stazeni; obsah se uloží do obsahově
adresovaného úložiště data/raw/<zdroj>/<sha256[:2]>/<sha256><přípona>. Opakované spuštění použije
již stažená data (stejná URL + parametry, HTTP 200/404 a soubor s odpovídajícím hashem), takže
pilot je reprodukovatelný a zdroje se zbytečně nezatěžují.

TLS se vždy ověřuje. Některé servery státní správy neposílají mezilehlý certifikát; ten doplňujeme
ze souboru certs/extra-intermediates.pem (stejně jako prohlížeč přes AIA), ověřování nevypínáme.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import certifi
import psycopg
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pvk import raw
from pvk.config import KOREN, Nastaveni, nastaveni

# Minimální rozestup dotazů na jeden server (sekundy). Šetrnost ke zdrojům.
ROZESTUPY = {
    "www.hlidacstatu.cz": 1.0,
    "api.vvz.nipez.cz": 0.35,
    "ares.gov.cz": 0.35,
}
VYCHOZI_ROZESTUP = 0.2
KESOVATELNE_STATUSY = (200, 404, 410)

_PRIPONY = {
    "application/pdf": ".pdf",
    "application/json": ".json",
    "text/html": ".html",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/csv": ".csv",
    "application/gzip": ".gz",
    "application/x-gzip": ".gz",
    "application/zip": ".zip",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "text/plain": ".txt",
}


def ca_bundle(data_dir: Path) -> str:
    """Důvěryhodné kořeny prostředí (REQUESTS_CA_BUNDLE / SSL_CERT_FILE / certifi) + chybějící mezilehlé."""
    zaklad = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE") or certifi.where()
    doplnek = KOREN / "certs" / "extra-intermediates.pem"
    if not doplnek.is_file():
        return zaklad
    obsah = Path(zaklad).read_bytes() + b"\n" + doplnek.read_bytes()
    cil = data_dir / "cache" / f"ca-bundle-{hashlib.sha256(obsah).hexdigest()[:16]}.pem"
    if not cil.is_file():
        cil.parent.mkdir(parents=True, exist_ok=True)
        cil.write_bytes(obsah)
    return str(cil)


@dataclass
class Odpoved:
    stazeni_id: int
    url: str
    status: int | None
    sha256: str | None
    cesta: Path | None
    content_type: str | None
    z_cache: bool
    cas_stazeni: datetime
    chyba: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.cesta is not None

    def obsah(self) -> bytes:
        if self.cesta is None:
            raise RuntimeError(f"stažení {self.url} nemá obsah ({self.status or self.chyba})")
        return self.cesta.read_bytes()

    def text(self, kodovani: str = "utf-8") -> str:
        return self.obsah().decode(kodovani, "replace")


class Stahovac:
    def __init__(self, conn: psycopg.Connection, konfigurace: Nastaveni | None = None, *, offline: bool = False):
        self.conn = conn
        self.nast = konfigurace or nastaveni()
        self.offline = offline
        self.uloziste = self.nast.data_dir / "raw"
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.nast.user_agent
        self.session.verify = ca_bundle(self.nast.data_dir)
        opakovani = Retry(
            total=3,
            connect=2,
            read=2,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "POST"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=opakovani))
        self._posledni: dict[str, float] = {}
        self._zamek = threading.Lock()

    # -- pomocné ---------------------------------------------------------------------------------
    def _pockej(self, host: str) -> None:
        rozestup = ROZESTUPY.get(host, VYCHOZI_ROZESTUP)
        with self._zamek:
            ted = time.monotonic()
            dalsi = self._posledni.get(host, 0.0) + rozestup
            if ted < dalsi:
                time.sleep(dalsi - ted)
            self._posledni[host] = time.monotonic()

    def _z_cache(self, zdroj: str, url: str, metoda: str, parametry: Mapping | None) -> Odpoved | None:
        row = self.conn.execute(
            """
            SELECT id, url, http_status, sha256, soubor, content_type, cas_stazeni FROM raw.stazeni
            WHERE zdroj = %s AND url = %s AND metoda = %s
              AND parametry IS NOT DISTINCT FROM %s::jsonb
              AND http_status = ANY(%s)
            ORDER BY cas_stazeni DESC LIMIT 1
            """,
            (
                zdroj,
                url,
                metoda,
                raw.kanonicky_json(parametry).decode() if parametry is not None else None,
                list(KESOVATELNE_STATUSY),
            ),
        ).fetchone()
        if not row:
            return None
        cesta = None
        if row["soubor"]:
            cesta = self.uloziste / row["soubor"]
            if not cesta.is_file() or _sha256_souboru(cesta) != row["sha256"].strip():
                return None
        return Odpoved(
            stazeni_id=row["id"],
            url=row["url"],
            status=row["http_status"],
            sha256=row["sha256"].strip() if row["sha256"] else None,
            cesta=cesta,
            content_type=row["content_type"],
            z_cache=True,
            cas_stazeni=row["cas_stazeni"],
        )

    # -- veřejné API -----------------------------------------------------------------------------
    def ziskej(
        self,
        zdroj: str,
        url: str,
        *,
        params: Mapping | None = None,
        metoda: str = "GET",
        json_telo: Mapping | None = None,
        obnov: bool = False,
        timeout: tuple[float, float] = (20, 180),
        pokusy: int | None = None,
        hlavicky: Mapping[str, str] | None = None,
    ) -> Odpoved:
        """Stáhne URL (nebo vrátí dříve stažené). Výsledek je vždy zapsán do raw.stazeni."""
        pripraveny = requests.Request(metoda, url, params=params).prepare()
        plna_url = pripraveny.url or url
        parametry = json_telo if json_telo is not None else None
        if not obnov:
            drivejsi = self._z_cache(zdroj, plna_url, metoda, parametry)
            if drivejsi is not None:
                return drivejsi
        cas = datetime.now(UTC)
        if self.offline:
            raise RuntimeError(f"offline režim: {plna_url} není v raw.stazeni")

        host = urlsplit(plna_url).hostname or ""
        self._pockej(host)
        session = self.session
        if pokusy is not None:
            session = requests.Session()
            session.headers.update(self.session.headers)
            session.verify = self.session.verify
            session.mount("https://", HTTPAdapter(max_retries=Retry(total=pokusy, backoff_factor=1)))
        try:
            with session.request(
                metoda,
                plna_url,
                json=json_telo,
                timeout=timeout,
                stream=True,
                headers=dict(hlavicky or {}),
            ) as r:
                status = r.status_code
                content_type = (r.headers.get("Content-Type") or "").split(";")[0].strip() or None
                sha, velikost, cesta_tmp = _stahni_do_souboru(r, self.uloziste)
        except requests.RequestException as e:
            chyba = f"{type(e).__name__}: {e}"[:2000]
            stazeni_id = raw.zapis_stazeni(
                self.conn,
                zdroj=zdroj,
                url=plna_url,
                cas_stazeni=cas,
                http_status=None,
                chyba=chyba,
                metoda=metoda,
                parametry=parametry,
            )
            self.conn.commit()
            return Odpoved(stazeni_id, plna_url, None, None, None, None, False, cas, chyba)

        relativni = f"{zdroj}/{sha[:2]}/{sha}{_pripona(content_type, plna_url)}"
        cil = self.uloziste / relativni
        if not cil.is_file():
            cil.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(cesta_tmp, cil)
        else:
            os.unlink(cesta_tmp)
        stazeni_id = raw.zapis_stazeni(
            self.conn,
            zdroj=zdroj,
            url=plna_url,
            cas_stazeni=cas,
            http_status=status,
            sha256=sha,
            velikost=velikost,
            soubor=relativni,
            content_type=content_type,
            metoda=metoda,
            parametry=parametry,
        )
        self.conn.commit()
        return Odpoved(stazeni_id, plna_url, status, sha, cil, content_type, False, cas)


def _stahni_do_souboru(r: requests.Response, uloziste: Path) -> tuple[str, int, str]:
    uloziste.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    velikost = 0
    fd, cesta = tempfile.mkstemp(prefix=".stahovani-", dir=uloziste)
    with os.fdopen(fd, "wb") as f:
        for kus in r.iter_content(chunk_size=1 << 16):
            if kus:
                h.update(kus)
                velikost += len(kus)
                f.write(kus)
    return h.hexdigest(), velikost, cesta


def _sha256_souboru(cesta: Path) -> str:
    h = hashlib.sha256()
    with cesta.open("rb") as f:
        for kus in iter(lambda: f.read(1 << 20), b""):
            h.update(kus)
    return h.hexdigest()


def _pripona(content_type: str | None, url: str) -> str:
    if content_type in _PRIPONY:
        return _PRIPONY[content_type]
    cesta = urlsplit(url).path.lower()
    for kandidat in (".csv.gz", ".xml.gz"):
        if cesta.endswith(kandidat):
            return kandidat
    pripona = Path(cesta).suffix
    if pripona and len(pripona) <= 5:
        return pripona
    return mimetypes.guess_extension(content_type or "") or ".bin"
