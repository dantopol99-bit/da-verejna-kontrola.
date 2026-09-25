"""Čisté funkce pilotu: analýza textu, skórování párování, klasifikace P3, křížová kontrola, P4, statistika."""

from datetime import date
from decimal import Decimal

import pytest
from PIL import Image, ImageDraw

from pvk.kotva import SubjektKotvy
from pvk.pilot import p2, p3, p4
from pvk.pilot.krizova import TextZaznamu, krizova_kontrola
from pvk.pilot.nazvy import normalizuj_nazev, podobnost
from pvk.pilot.statistika import Podil
from pvk.text import analyza as a
from pvk.text.extrakce import cerne_bloky, rozpoznej_format
from pvk.zdroje.dotace import Prijemce
from pvk.zdroje.rs import StranaRS, ZaznamRS
from pvk.zdroje.vvz import OrganizaceVVZ, SmlouvaVVZ

P2 = {
    "okno_dni_datum_uzavreni": 30,
    "okno_dni_bez_data_uzavreni": [-180, 7],
    "tolerance_castky": 0.10,
    "sazby_dph": [0.21, 0.12],
    "vahy": {"ico": 0.4, "datum": 0.3, "castka": 0.3},
    "prah_pravdepodobne": 0.70,
    "max_skore_heuristiky": 0.999,
}


def zaznam(**kw) -> ZaznamRS:
    zaklad = dict(
        id_verze="1", id_smlouvy="1", odkaz="https://smlouvy.gov.cz/smlouva/1", cas_zverejneni=None,
        subjekt=StranaRS("Kraj", "70889546"), smluvni_strany=[StranaRS("Firma", "26014998")], predmet=None,
        datum_uzavreni=date(2025, 6, 13), cislo_smlouvy=None, hodnota_bez_dph=None, hodnota_vcetne_dph=None,
        cizi_mena_hodnota=None, cizi_mena=None, duvod_neuvedeni_ceny=None, navazany_zaznam=None, prilohy=[],
        platny=True, zdroj="test",
    )
    zaklad.update(kw)
    return ZaznamRS(**zaklad)


SMLOUVA = SmlouvaVVZ("CON-1", None, date(2025, 6, 13), [], Decimal("5458000.01"), "CZK",
                     [OrganizaceVVZ("ORG-4", "26014998", "Firma")])


# --- analýza textu ---


def test_najdi_castky_v_ruznych_zapisech():
    text = ("Cena díla činí 20.068.576,42 Kč bez DPH. Záloha 5 000 Kč. Nájemné 12 000,- měsíčně. "
            "Poplatek CZK 1 500. Pokuta 500 EUR.")
    hodnoty = {(n.hodnota, n.mena) for n in a.najdi_castky(text)}
    assert (Decimal("20068576.42"), "CZK") in hodnoty
    assert (Decimal("5000"), "CZK") in hodnoty
    assert (Decimal("12000"), "CZK") in hodnoty
    assert (Decimal("1500"), "CZK") in hodnoty
    assert (Decimal("500"), "EUR") in hodnoty


def test_cenovy_kontext():
    (cena,) = [n for n in a.najdi_castky("Kupní cena je 100 000 Kč.")]
    (jiny,) = [n for n in a.najdi_castky("Pojistné plnění do výše 100 000 Kč za škodu.")]
    assert cena.cenovy_kontext and cena.klicove_slovo in {"kupní", "cena"}
    assert not jiny.cenovy_kontext


def test_castka_v_textu_s_toleranci_zaokrouhleni():
    nalezy = a.najdi_castky("cena 20.068.576,42 Kč")
    assert a.castka_v_textu(Decimal("20068576"), nalezy)  # zrcadlo zaokrouhluje na celé Kč
    assert a.castka_v_textu(Decimal("20068500"), nalezy) is None


def test_data_a_podpis():
    text = "V Praze dne 3. 9. 2026 ... Datum: 2026.09.24 10:23:45 +02'00' ... platí do 31. prosince 2027"
    data = {(d.datum, d.podpis) for d in a.najdi_data(text)}
    assert (date(2026, 9, 3), True) in data
    assert (date(2026, 9, 24), True) in data
    assert (date(2027, 12, 31), False) in data


@pytest.mark.parametrize("text", ["IČO: 00255513", "IČ 002 55 513", "IČ: 255513", "ič.00255513x"[:-1]])
def test_ico_v_textu(text):
    assert a.ico_v_textu("00255513", text)


def test_ico_v_textu_nenajde_cizi_cislo():
    assert a.ico_v_textu("00255513", "telefon 100255513 a IČO 45023522") is None


def test_znacky_znecitelneni():
    assert a.znacky_znecitelneni("Jméno: XXXXXXX, bytem ██████")
    assert a.znacky_znecitelneni("údaj [anonymizováno]")
    assert not a.znacky_znecitelneni("dne xx.xx.xxxx, cena 10 Kč")
    assert a.RE_NAZEV_ZNECITELNENI.search("Smlouva_anonym.pdf")
    assert a.RE_NAZEV_ZNECITELNENI.search("462_2026_Redigováno.pdf")


def test_doba_plneni():
    assert a.doba_plneni("Tento souhlas je udělen na dobu neurčitou.")["neurcita"] is None
    assert a.doba_plneni("Smlouva se uzavírá na dobu neurčitou.")["neurcita"] is True
    assert a.doba_plneni("Nájem se sjednává na dobu určitou od 1. 1. 2026 do 31. 12. 2028.")["delka_dni"] == 1095
    assert a.doba_plneni("Služby budou poskytovány po dobu 4 let.")["delka_dni"] == 1460


def test_cerne_bloky_ve_skenu():
    img = Image.new("L", (1200, 1700), 255)
    kresba = ImageDraw.Draw(img)
    kresba.rectangle([200, 300, 600, 340], fill=0)  # začernění řádku
    kresba.rectangle([200, 500, 700, 503], fill=0)  # tenká linka (není začernění)
    assert cerne_bloky(img) == 1


def test_rozpoznani_formatu():
    assert rozpoznej_format(b"%PDF-1.7 ...") == "pdf"
    assert rozpoznej_format(b"{\\rtf1 ...") == "rtf"
    assert rozpoznej_format(b"\xd0\xcf\x11\xe0....") == "ole"
    assert rozpoznej_format(b"\x89PNG....") == "obrazek"


# --- P2: skórování ---


def test_skore_presna_shoda_je_pod_jistotou():
    z = zaznam(hodnota_vcetne_dph=Decimal("6604180"))
    s = p2.skore(SMLOUVA, z, {"70889546"}, date(2025, 7, 2), P2)
    assert s["shoda_ico"] and s["shoda_data"] == 1.0 and s["shoda_castky"] > 0.99
    assert s["skore"] == 0.999  # heuristika nikdy nedosáhne 1 (vyhrazeno doloženým vazbám)
    assert s["porovnani_castky"] == "s_dph/1.21"


def test_skore_bez_shody_ico_je_nula():
    z = zaznam(smluvni_strany=[StranaRS("Jiná", "45023522")], hodnota_bez_dph=Decimal("5458000"))
    assert p2.skore(SMLOUVA, z, {"70889546"}, None, P2)["skore"] == 0.0


def test_skore_datum_a_castka_mimo_toleranci():
    z = zaznam(datum_uzavreni=date(2025, 8, 1), hodnota_bez_dph=Decimal("7000000"))
    s = p2.skore(SMLOUVA, z, {"70889546"}, None, P2)
    assert s["shoda_data"] == 0.0 and s["shoda_castky"] == 0.0 and s["skore"] == 0.4
    assert s["skore"] < P2["prah_pravdepodobne"]


def test_skore_bez_data_uzavreni_v_oznameni():
    sm = SmlouvaVVZ("CON-1", None, None, [], None, None, SMLOUVA.dodavatele)
    z = zaznam(datum_uzavreni=date(2025, 6, 13))
    assert p2.shoda_data(sm, z, date(2025, 7, 2), P2) == 0.5
    assert p2.shoda_data(sm, z, date(2026, 7, 2), P2) == 0.0


# --- P3 ---


@pytest.mark.parametrize(
    ("text", "verdikt"),
    [
        ("Nájemní smlouva se uzavírá na dobu neurčitou. Nájemné činí 10 000 Kč měsíčně.", "ano"),
        ("Smlouva na dobu určitou od 1. 1. 2026 do 31. 12. 2028. Roční poplatek za licenci 50 000 Kč ročně.", "ano"),
        ("Smlouva se uzavírá na dobu neurčitou. Cena za hodinu práce 800 Kč/hod.", "ne"),
        ("Smlouva se uzavírá na dobu neurčitou. Odměna bude hrazena podle skutečného rozsahu.", "ne"),
        ("Nájem na dobu neurčitou. Nájemné 5 000 Kč měsíčně, služby 1 000 Kč ročně.", "nejasne"),
        ("Nájem na dobu neurčitou. Nájemné za byt 5 000 Kč měsíčně, za garáž 1 000 Kč měsíčně.", "nejasne"),
    ],
)
def test_p3_klasifikace(text, verdikt):
    k = p3.klasifikuj(text)
    assert k["opakovane"] and k["verdikt"] == verdikt


def test_p3_mesicni_castka_na_rok():
    k = p3.klasifikuj("Nájemní smlouva se uzavírá na dobu neurčitou. Nájemné činí 10 000 Kč měsíčně.")
    assert k["rocni_hodnota"] == Decimal("120000")


def test_p3_jednorazove_plneni_neni_opakovane():
    assert not p3.klasifikuj("Kupní smlouva. Kupní cena 50 000 Kč je splatná do 14 dnů.")["opakovane"]


# --- křížová kontrola ---


def test_krizova_kontrola_shoda():
    z = zaznam(hodnota_bez_dph=Decimal("100000"), datum_uzavreni=date(2026, 9, 3))
    text = "Objednatel IČO 70889546, zhotovitel IČO 26014998. Cena 100 000 Kč bez DPH. V Praze dne 3. 9. 2026"
    vysledky, vyjimky = krizova_kontrola(z, TextZaznamu(text, "https://smlouvy.gov.cz/smlouva/soubor/1/a.pdf"))
    assert vysledky["castka"] == "shoda" and vysledky["datum_uzavreni"] == "shoda"
    assert vysledky["ico"] == {"70889546": "nalezeno", "26014998": "nalezeno"}
    assert vyjimky == []


def test_krizova_kontrola_neshody():
    z = zaznam(hodnota_bez_dph=Decimal("100000"), datum_uzavreni=date(2026, 9, 1),
               cas_zverejneni=None)
    text = "Objednatel IČO 70889546, dodavatel IČO 45023522. Cena díla 250 000 Kč. V Brně dne 5. 9. 2026"
    vysledky, vyjimky = krizova_kontrola(z, TextZaznamu(text, None))
    udaje = {v["udaj"] for v in vyjimky}
    assert vysledky["castka"] == "neshoda" and "castka" in udaje
    assert "ico_strana" in udaje  # 26014998 v textu chybí, text uvádí jiné IČO
    assert vysledky["datum_uzavreni"] == "neshoda" and "datum_uzavreni" in udaje
    # výjimky neobsahují citace textu smlouvy
    assert all("Brně" not in v["nalezeno_v_textu"] for v in vyjimky)


def test_krizova_kontrola_castka_jen_v_priloze():
    z = zaznam()
    vysledky, vyjimky = krizova_kontrola(z, TextZaznamu("Kupní cena činí 80 000 Kč. IČO 70889546, 26014998", None))
    assert vysledky["castka"] == "bez_castky_v_metadatech"
    assert [v["udaj"] for v in vyjimky] == ["castka_chybi_v_metadatech"]


def test_krizova_kontrola_prepocet_dph():
    z = zaznam(hodnota_bez_dph=Decimal("100000"))
    vysledky, _ = krizova_kontrola(z, TextZaznamu("Cena včetně DPH 121 000 Kč. IČO 70889546 a 26014998", None))
    assert vysledky["castka"] == "shoda_po_prepoctu_dph"


# --- P4 ---


class FalesnaKotva:
    def __init__(self, subjekty, hledani=None):
        self.subjekty = subjekty
        self.hledani = hledani or []

    def subjekt_podle_ico(self, ico):
        return self.subjekty.get(ico)

    def hledej_podle_nazvu(self, nazev, max_vysledku=5):
        return self.hledani


def prijemce(nazev, ico, fo=False):
    return Prijemce("test", "1", nazev, ico, ico, None, fo, {})


def ares(ico, nazev, fo=False):
    return SubjektKotvy(ico, nazev, "101" if fo else "112", fo, None, None, "ares")


def test_p4_kategorie():
    k = FalesnaKotva({"03513386": ares("03513386", "GoodAccess s.r.o.")})
    assert p4.sparuj(prijemce("GOODACCESS, s. r. o.", "03513386"), k, 0.8)["kategorie"] == "ico_ares_shoda_nazvu"
    assert p4.sparuj(prijemce("Úplně jiná firma a.s.", "03513386"), k, 0.8)["kategorie"] == "ico_ares_jiny_nazev"
    assert p4.sparuj(prijemce("X", "00255513"), k, 0.8)["kategorie"] == "ico_neexistuje_v_ares"
    assert p4.sparuj(prijemce("X", "00255514"), k, 0.8)["kategorie"] == "ico_neplatne"
    assert p4.sparuj(prijemce(None, None, fo=True), k, 0.8)["kategorie"] == "fo_bez_ico"
    k2 = FalesnaKotva({}, [ares("03513386", "GoodAccess s.r.o.")])
    assert p4.sparuj(prijemce("GoodAccess s.r.o.", None), k2, 0.8)["kategorie"] == "nazev_ares_jednoznacne"


def test_p4_slozeni_ramce():
    ramec = [prijemce("A", "03513386"), prijemce(None, None, True), prijemce(None, None, True), prijemce("B", None)]
    assert p4.slozeni_ramce(ramec) == {"fo_bez_ico": 2, "fo_s_ico": 0, "po_s_ico": 1, "po_bez_ico": 1}


# --- názvy a statistika ---


def test_normalizace_nazvu():
    assert normalizuj_nazev("STAVEBNÍ SPOLEČNOST H a T, spol. s r. o.") == "stavebni spolecnost h a t"
    assert podobnost("Obec Pstruží", "Obec Pstruží") == 1.0
    assert podobnost("Královéhradecký kraj", "Kralovehradecky kraj") == 1.0
    assert podobnost("ABC s.r.o.", "XYZ a.s.") < 0.5


def test_wilsonuv_interval():
    p = Podil(170, 200)
    dolni, horni = p.interval
    assert dolni < 0.85 < horni and 0.79 < dolni < 0.80 and 0.89 < horni < 0.90
    assert Podil(0, 50).interval[0] == 0.0 and Podil(0, 0).hodnota is None
