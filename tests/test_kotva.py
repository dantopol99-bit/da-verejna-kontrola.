"""Adaptér kotvy: subjekt_podle_ico(). V pilotu ARES, bez lokální kopie registru."""

from datetime import date

import pytest

from pvk import kotva
from pvk.kotva import AresKotva, DbKotva, subjekt_podle_ico


class FalesnaOdpoved:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


ARES_03513386 = {
    "ico": "03513386",
    "obchodniJmeno": "GoodAccess s.r.o.",
    "pravniForma": "112",
    "datumVzniku": "2014-10-23",
    "sidlo": {"textovaAdresa": "Špitálské náměstí 3517/1b, 40001 Ústí nad Labem"},
}
ARES_OSVC = {"ico": "67210287", "obchodniJmeno": "Xuân Thang Truong", "pravniForma": "101"}


@pytest.fixture
def ares(monkeypatch):
    k = AresKotva(user_agent="test")
    k.ROZESTUP = 0
    volani = []

    def get(url, timeout):
        volani.append(url)
        ico = url.rsplit("/", 1)[1]
        data = {"03513386": ARES_03513386, "67210287": ARES_OSVC}.get(ico)
        return FalesnaOdpoved(200, data) if data else FalesnaOdpoved(404)

    monkeypatch.setattr(k.session, "get", get)
    k.volani = volani
    return k


def test_subjekt_podle_ico(ares):
    s = subjekt_podle_ico("3513386", kotva=ares)
    assert s.ico == "03513386" and s.nazev == "GoodAccess s.r.o."
    assert s.je_fyzicka_osoba is False and s.datum_vzniku == date(2014, 10, 23) and s.zdroj == "ares"


def test_fyzicka_osoba_je_rozpoznana(ares):
    assert subjekt_podle_ico("67210287", kotva=ares).je_fyzicka_osoba is True


def test_neexistujici_ico(ares):
    assert subjekt_podle_ico("00255513", kotva=ares) is None


def test_neplatne_ico_se_neposila_do_ares(ares):
    assert subjekt_podle_ico("00255514", kotva=ares) is None
    assert subjekt_podle_ico("abc", kotva=ares) is None
    assert ares.volani == []


def test_jen_pametova_cache(ares, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subjekt_podle_ico("03513386", kotva=ares)
    subjekt_podle_ico("03513386", kotva=ares)
    assert len(ares.volani) == 1
    assert list(tmp_path.iterdir()) == []  # nic se neukládá na disk


def test_budouci_napojeni_na_databazi_kotvy():
    with pytest.raises(NotImplementedError):
        DbKotva("postgresql://kotva").subjekt_podle_ico("03513386")


@pytest.mark.parametrize(
    ("kod", "fo"), [("101", True), ("100", True), ("424", True), ("112", False), ("801", False), (None, None)]
)
def test_pravni_formy(kod, fo):
    assert kotva.je_fyzicka_osoba(kod) is fo
