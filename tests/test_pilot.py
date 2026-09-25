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


def test_cislo_navazujici_na_pismeno_neni_castka():
    assert [n.hodnota for n in a.najdi_castky("cena 1 200 Kč/m2 500 Kč")] == [Decimal("1200"), Decimal("500")]
    assert a.najdi_castky("Cena dle parity/m3            EUR") == []


@pytest.mark.parametrize("text, cena", [
    ("Kupní cena činí 80 000 Kč.", True),
    ("Cena bez DPH 100 000 Kč, sazba DPH 21 %, cena s DPH 121 000 Kč.", True),
    ("Roční pojistné činí 50 000 Kč.", True),
    ("Hodinová sazba advokátní kanceláře se sjednává ve výši 3.600 Kč bez DPH.", False),
    ("Cena za dopravu 25 Kč/m3/km.", False),
    ("Odměna 1 500 Kč za hodinu.", False),
    ("Zhotovitel zaplatí smluvní pokutu ve výši 5 000 Kč.", False),
    ("Spoluúčast nájemce nepřesáhne 100.000 Kč na jednu pojistnou událost.", False),
    ("Klient může poukázky objednat v hodnotě vyšší než 150 000 Kč.", False),
    ("Zhotovitel doloží pojištění odpovědnosti s limitem plnění 5 000 000 Kč.", False),
    ("Poukázky v hodnotě (nad 150 000 Kč) se nedoručují.", False),
    ("Žadatel uhradil pojistné ve výši minimálně 1000,- Kč.", False),
    ("Nájemce se zavazuje platit roční nájemné ve výši 12 Kč bez DPH.", True),
])
def test_cena_plneni(text, cena):
    n = a.najdi_castky(text)[0]
    assert a.je_cena_plneni(text, n) is cena


def test_hodnota_v_textu_bez_meny():
    assert a.hodnota_v_textu(Decimal("99000"), "Položka | 99 000,00 | 1 ks")
    assert a.hodnota_v_textu(Decimal("155000"), "celkem 155.000, - CZK")
    assert a.hodnota_v_textu(Decimal("70325"), "70 325.00")
    assert a.hodnota_v_textu(Decimal("1122107"), "cena 1 122 106,90")  # zrcadlo zaokrouhluje na celé Kč
    assert a.hodnota_v_textu(Decimal("99000"), "tel. 199 000 111") is None
    assert a.hodnota_v_textu(Decimal("500"), "balení 500 ml") is None  # malé číslo bez měny se nehledá


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
    # zástupný údaj za dvojtečkou, v závorce nebo samostatně na řádku
    assert a.znacky_znecitelneni("Kontaktní osoba: anonymizováno\nTelefon: 123")
    assert a.znacky_znecitelneni("Zastoupen (osobní údaj), jednatelem")
    assert a.znacky_znecitelneni("Telefon:\n  znečitelněno\nE-mail:")
    # doložky o uveřejnění nejsou znečitelněný text
    assert not a.znacky_znecitelneni("informace, které by jinak podléhaly znečitelnění, v registru smluv")
    assert not a.znacky_znecitelneni("po znečitelnění údajů (metadata)")
    assert not a.znacky_znecitelneni("zašle kopii objednávky se začerněnými údaji")
    assert not a.znacky_znecitelneni("Smlouva bude anonymizována tak, aby neobsahovala osobní údaje.")
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


def test_krizova_kontrola_ico_nelze_overit():
    z = zaznam(hodnota_bez_dph=Decimal("100000"))
    # text uvádí jen IČO publikujícího subjektu (70889546), IČO protistrany (26014998) ne
    _, vyjimky = krizova_kontrola(z, TextZaznamu("Objednatel IČO 70889546. Cena 100 000 Kč.", None))
    (v,) = [v for v in vyjimky if v["udaj"] == "ico_strana"]
    assert v["navrh_verdiktu"].startswith("NELZE OVĚŘIT – text uvádí jen IČO jiné strany")
    # text neuvádí žádné IČO
    _, vyjimky = krizova_kontrola(z, TextZaznamu("Objednávka kancelářských potřeb. Cena 100 000 Kč.", None))
    assert {v["udaj"] for v in vyjimky} == {"ico_subjekt", "ico_strana"}
    assert all("neuvádí žádné IČO" in v["navrh_verdiktu"] for v in vyjimky)


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


def _minimalni_pdf(obsah: bytes) -> bytes:
    """Jednostránkové PDF s daným obsahovým proudem (Helvetica jako F1)."""
    objekty = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(obsah)).encode() + b" >>\nstream\n" + obsah + b"\nendstream",
    ]
    vystup = b"%PDF-1.4\n"
    pozice = []
    for i, o in enumerate(objekty, 1):
        pozice.append(len(vystup))
        vystup += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(vystup)
    vystup += f"xref\n0 {len(objekty) + 1}\n0000000000 65535 f \n".encode()
    vystup += b"".join(f"{p:010d} 00000 n \n".encode() for p in pozice)
    vystup += f"trailer\n<< /Size {len(objekty) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return vystup


def test_zacerneni_ve_vektorovem_pdf(tmp_path):
    from pvk.text.extrakce import vektorove_cerne_obdelniky

    # řádek textu se začerněným jménem + velká černá plocha bez textu (např. logo) + pruh v zápatí
    # + černé záhlaví tabulky s bílým textem (čitelné, nepočítá se)
    obsah = (b"BT /F1 11 Tf 72 700 Td (Zastoupen:) Tj ET\n"
             b"0 g 140 697 90 12 re f\n"
             b"0 g 72 300 200 150 re f\n"
             b"0 g 20 10 300 12 re f\n"
             b"0 g 72 600 150 12 re f\n"
             b"BT 1 g /F1 10 Tf 75 602 Td (Cena bez DPH) Tj ET\n")
    cesta = tmp_path / "zacerneni.pdf"
    cesta.write_bytes(_minimalni_pdf(obsah))
    assert vektorove_cerne_obdelniky(cesta) == 1


def test_p3_slouceni_variant_dph():
    assert p3.sluc_dph({Decimal("11880000"), Decimal("14374800"), Decimal("2494800")}) == {Decimal("11880000")}
    assert p3.sluc_dph({Decimal("1668264"), Decimal("1701648")}) == {Decimal("1668264"), Decimal("1701648")}


def test_p3_rocni_castka_bez_a_s_dph_je_jednoznacna():
    k = p3.klasifikuj("Smlouva o poskytování služeb na dobu neurčitou. Cena činí 100 000 Kč bez DPH ročně, "
                      "tj. 121 000 Kč včetně DPH ročně.")
    assert k["verdikt"] == "ano" and k["rocni_hodnota"] == Decimal("100000")


def test_p3_rocni_smlouva_s_celkovou_cenou():
    k = p3.klasifikuj("Služby budou poskytovány v období od 1. 1. 2026 do 31. 12. 2026. Celková cena 240 000 Kč.")
    assert k["verdikt"] == "ano" and k["rocni_hodnota"] == Decimal("240000")


def test_p3_jednotkova_cena_neni_rocni_hodnota():
    k = p3.klasifikuj("Nájemní smlouva na dobu neurčitou. Nájemné 120 Kč/m2 ročně.")
    assert k["verdikt"] == "ne"


def test_p3_zarucni_doba_neni_doba_plneni():
    k = p3.klasifikuj("Kupní smlouva. Kupní cena 50 000 Kč. Záruční doba činí 60 měsíců, tj. po dobu 5 let.")
    assert not k["opakovane"]


def test_krizova_kontrola_vysvetlitelne_castky():
    z = zaznam(hodnota_bez_dph=Decimal("1998000"))
    vysledky, vyjimky = krizova_kontrola(z, TextZaznamu("Paušál 33 300 Kč měsíčně. IČO 70889546, 26014998", None))
    assert vysledky["castka"] == "shoda_nasobek_periody" and vyjimky == []
    z = zaznam(hodnota_bez_dph=Decimal("68650"))
    text = "Předpokládaná cena 62 000 Kč, paušál 5 000 Kč a paušál 1 650 Kč. IČO 70889546, 26014998"
    vysledky, _ = krizova_kontrola(z, TextZaznamu(text, None))
    assert vysledky["castka"] == "shoda_souctu_polozek"
