"""Oficiální stahovač registru smluv (D-030) nad vzorovými daty – bez sítě.

Oficiální zdroj (data.smlouvy.gov.cz, smlouvy.gov.cz) nebyl z prostředí pilotu dostupný; testy ověřují,
že stahovač stačí spustit: výběr z denních dumpů, parsování a kontrola hashe příloh proti oficiálním metadatům.
"""

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from pvk.config import nastaveni
from pvk.http import Odpoved
from pvk.zdroje.hlidac import HlidacRS
from pvk.zdroje.registr_smluv import DATA_URL, NeshodaHashe, OficialniRS, parsuj_dump

DUMP = Path(__file__).parent / "fixtures" / "rs_dump_ukazka.xml"


class FalesnyStahovac:
    """Místo sítě vrací připravené soubory podle URL (jinak 404) a zaznamenává dotazy."""

    def __init__(self, soubory: dict[str, Path]):
        self.soubory = soubory
        self.dotazy: list[str] = []

    def ziskej(self, zdroj: str, url: str, **_) -> Odpoved:
        self.dotazy.append(url)
        cesta = self.soubory.get(url)
        if cesta is None:
            return Odpoved(len(self.dotazy), url, 404, None, None, None, False, datetime.now(UTC))
        sha = hashlib.sha256(cesta.read_bytes()).hexdigest()
        return Odpoved(len(self.dotazy), url, 200, sha, cesta, "application/octet-stream", False, datetime.now(UTC))


def test_dostupnost_podle_indexu_dumpu():
    assert OficialniRS(FalesnyStahovac({f"{DATA_URL}/index.xml": DUMP})).dostupny()
    assert not OficialniRS(FalesnyStahovac({})).dostupny()


def test_vzorek_z_dennich_dumpu():
    den = date(2026, 9, 1)
    s = FalesnyStahovac({f"{DATA_URL}/dump_{den:%Y_%m_%d}.xml": DUMP})
    vzorek = OficialniRS(s).vzorek(5, den, date(2026, 9, 3), seed=1)
    # neplatná verze se vyřadí, chybějící dump (404) se přeskočí
    assert [z.id_verze for z, _xml, _odp in vzorek] == ["39673953"]
    z, xml, odp = vzorek[0]
    assert z.prilohy[0].sha256 and b"<zaznam" in xml and odp.status == 200


def test_priloha_overi_hash_z_oficialnich_metadat(tmp_path):
    z = next(z for z, _ in parsuj_dump(DUMP) if z.platny)
    obsah = b"%PDF-1.4 vzorova priloha"
    soubor = tmp_path / "priloha.pdf"
    soubor.write_bytes(obsah)
    pr = replace(z.prilohy[0], sha256=hashlib.sha256(obsah).hexdigest())
    rs = OficialniRS(FalesnyStahovac({pr.url_original: soubor}))
    assert rs.priloha(pr).sha256 == pr.sha256
    soubor.write_bytes(obsah + b" pozmeneno")  # jiný soubor než v metadatech registru
    with pytest.raises(NeshodaHashe) as chyba:
        rs.priloha(pr)
    assert chyba.value.odpoved.status == 200 and chyba.value.skutecny != pr.sha256


def test_provoz_jen_z_oficialnich_zdroju(monkeypatch):
    monkeypatch.delenv("PVK_RS_BACKEND", raising=False)
    assert nastaveni().rs_backend == "oficialni"
    with pytest.raises(PermissionError):
        HlidacRS(FalesnyStahovac({}))  # zrcadlo jen s pilot=True
