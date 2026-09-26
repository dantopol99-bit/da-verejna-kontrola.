"""Parsery zdrojů nad fixture daty (výřezy skutečných odpovědí bez osobních údajů a syntetický dump)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from pvk.zdroje.dotace import je_antibot_vyzva
from pvk.zdroje.hlidac import parsuj_detail, parsuj_vyhledavani
from pvk.zdroje.registr_smluv import parsuj_dump
from pvk.zdroje.rs import na_decimal
from pvk.zdroje.vvz import parsuj_eforms

FIXTURES = Path(__file__).parent / "fixtures"


def test_detail_zrcadla_rs():
    z = parsuj_detail((FIXTURES / "hs_detail_39673953.html").read_text(encoding="utf-8"), "39673953")
    assert z.platny and z.id_smlouvy == "37303957" and z.odkaz == "https://smlouvy.gov.cz/smlouva/39673953"
    assert z.subjekt.ico == "00255513" and z.subjekt.platce
    assert [s.ico for s in z.smluvni_strany] == ["45023522"] and z.smluvni_strany[0].prijemce
    assert (z.hodnota_bez_dph, z.hodnota_vcetne_dph) == (Decimal("20068576"), Decimal("24282977"))
    assert z.datum_uzavreni == date(2026, 9, 24) and z.cislo_smlouvy == "MEUHOR02073931"
    assert z.cas_zverejneni.isoformat() == "2026-09-25T08:55:25+02:00"
    assert len(z.prilohy) == 1
    p = z.prilohy[0]
    assert p.sha256 == "cce8e2e21834acf2c46843248dd8249fc1726263df54aaa4b9d8dc1d30aa17c1"
    assert p.url_original.startswith("https://smlouvy.gov.cz/smlouva/soubor/47825737/")
    assert p.url_stazeni.startswith("https://www.hlidacstatu.cz/KopiePrilohy/39673953?hash=")


def test_detail_neodpovidajici_verze_je_chyba():
    import pytest

    with pytest.raises(ValueError):
        parsuj_detail((FIXTURES / "hs_detail_39673953.html").read_text(encoding="utf-8"), "1")


def test_vyhledavani_zrcadla():
    celkem, radky = parsuj_vyhledavani((FIXTURES / "hs_hledani.html").read_text(encoding="utf-8"))
    assert celkem == 5
    podle_id = {r.id_verze: r for r in radky}
    assert podle_id["33696136"].podepsano == date(2025, 6, 13)
    assert podle_id["33696136"].hodnota_s_dph == Decimal("6604180")


def test_dump_registru_smluv():
    zaznamy = list(parsuj_dump(FIXTURES / "rs_dump_ukazka.xml"))
    assert [z.id_verze for z, _ in zaznamy] == ["39673953", "39673961"]
    prvni, xml = zaznamy[0]
    assert prvni.platny and prvni.subjekt.ico == "00255513" and prvni.smluvni_strany[0].ico == "45023522"
    assert prvni.hodnota_bez_dph == Decimal("20068576.42") and prvni.datum_uzavreni == date(2026, 8, 31)
    assert prvni.prilohy[0].sha256.startswith("cce8e2e2") and b"zaznam" in xml
    druhy, _ = zaznamy[1]
    assert not druhy.platny and (druhy.cizi_mena_hodnota, druhy.cizi_mena) == (Decimal("1200"), "EUR")
    # strana bez IČO se do raw ukládá bez názvu (minimalizace osobních údajů)
    assert druhy.jako_dict()["smluvni_strany"][0]["nazev"] is None


def test_formular_eforms_z_vvz():
    import json

    data = json.loads((FIXTURES / "vvz_F2025-035449.json").read_text(encoding="utf-8"))
    o = parsuj_eforms(data["souhrn"], data["deti"])
    assert o.ev_cislo_zakazky == "Z2025-010690" and o.druh_formulare == "29" and o.vybran_dodavatel
    assert [z.ico for z in o.zadavatele] == ["70889546"]
    assert o.predpokladana_hodnota == Decimal("6262283.0")
    (sm,) = o.smlouvy
    assert sm.datum_uzavreni == date(2025, 6, 13) and sm.hodnota == Decimal("5458000.01") and sm.mena == "CZK"
    assert [d.ico for d in sm.dodavatele] == ["26014998"] and sm.id_verzi_rs == []


def test_odkaz_do_rs_z_bt151():
    from pvk.zdroje.vvz import SmlouvaVVZ

    sm = SmlouvaVVZ("CON-1", None, None, ["https://smlouvy.gov.cz/smlouva/39384009?backlink=o7lju",
                                          "https://example.cz/profil"], None, None, [])
    assert sm.id_verzi_rs == ["39384009"]


def test_na_decimal():
    assert na_decimal("20 068 576 Kč") == Decimal("20068576")
    assert na_decimal("1 234,50") == Decimal("1234.50")
    assert na_decimal("1.234.567,00") == Decimal("1234567.00")
    assert na_decimal("") is None and na_decimal("abc") is None


def test_rozpoznani_antibot_vyzvy():
    assert je_antibot_vyzva(b'<html><script>window["bobcmn"] = "1011"; /TSPD/08f</script>')
    assert not je_antibot_vyzva(b"PRIJEMCE;ICO;CASTKA\n")
