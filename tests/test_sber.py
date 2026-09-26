"""Sběr do raw (blok 2) nad vzorovými daty – bez sítě.

Stahovače blokovaných zdrojů (registr smluv, NEN, ISVZ, CEDR) nešlo z cloudu spustit proti zdroji;
testy ověřují, že poběží jedním příkazem: evidence běhu, původ záznamů, pouze INSERT, žádné
duplicity při opakovaném běhu, přeskočení nedostupného zdroje a minimalizace osobních údajů.
"""

import gzip
import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import openpyxl
import psycopg
import pytest
import requests

from pvk import raw
from pvk.http import Odpoved
from pvk.sber import Sberac, sberace, spust
from pvk.sber import __main__ as cli
from pvk.zdroje import dotace as dotace_zdroje
from pvk.zdroje import registr_smluv as rs
from pvk.zdroje import vvz, zaregistruj_zdroje

DUMP = Path(__file__).parent / "fixtures" / "rs_dump_ukazka.xml"
OD, DO = date(2026, 8, 26), date(2026, 9, 26)


class FalesnyStahovac:
    """Místo sítě vrací připravená data podle úplné URL (jinak spojení odmítnuto); každý dotaz
    zapíše do raw.stazeni jako skutečný stahovač (včetně beh_id)."""

    def __init__(self, conn, tmp: Path, data: dict[str, bytes | tuple[bytes, dict]]):
        self.conn, self.tmp, self.data, self.beh_id, self.dotazy = conn, tmp, data, None, []

    def ziskej(self, zdroj, url, *, params=None, **_):
        plna = requests.Request("GET", url, params=params).prepare().url
        self.dotazy.append(plna)
        cas = datetime.now(UTC)
        polozka = self.data.get(plna)
        if polozka is None:
            sid = raw.zapis_stazeni(self.conn, zdroj=zdroj, url=plna, cas_stazeni=cas, http_status=None,
                                    chyba="ConnectionError: spojení ukončeno", beh_id=self.beh_id)
            return Odpoved(sid, plna, None, None, None, None, False, cas, "ConnectionError: spojení ukončeno")
        obsah, hlavicky = polozka if isinstance(polozka, tuple) else (polozka, {})
        sha = hashlib.sha256(obsah).hexdigest()
        cesta = self.tmp / sha
        cesta.write_bytes(obsah)
        sid = raw.zapis_stazeni(self.conn, zdroj=zdroj, url=plna, cas_stazeni=cas, http_status=200, sha256=sha,
                                velikost=len(obsah), soubor=sha, hlavicky=hlavicky, beh_id=self.beh_id)
        return Odpoved(sid, plna, 200, sha, cesta, None, False, cas, hlavicky=hlavicky)


def _url(url, **params):
    return requests.Request("GET", url, params=params or None).prepare().url


def _gz_csv(radky: list[dict]) -> bytes:
    buf = io.StringIO()
    buf.write(",".join(radky[0]) + "\n")
    for r in radky:
        buf.write(",".join(str(v) for v in r.values()) + "\n")
    return gzip.compress(buf.getvalue().encode())


@pytest.fixture
def conn(db):
    zaregistruj_zdroje(db)
    return db


def _beh(conn, beh_id):
    return conn.execute("SELECT * FROM raw.beh_prehled WHERE id = %s", (beh_id,)).fetchone()


def _zaznamy(conn, zdroj):
    return conn.execute("SELECT * FROM raw.zaznam WHERE zdroj = %s ORDER BY id_ve_zdroji", (zdroj,)).fetchall()


def test_nedostupny_zdroj_se_preskoci_se_zaznamem_v_evidenci(conn, tmp_path):
    s = FalesnyStahovac(conn, tmp_path, {})
    for zdroj in ("registr_smluv", "nen", "isvz", "cedr"):
        beh_id, stav = spust(conn, s, sberace.SBERACE[zdroj], OD, DO)
        b = _beh(conn, beh_id)
        assert stav == b["stav"] == "preskoceno" and b["konec"] is not None and b["pocet_chyb"] == 1
        assert "nedostupný" in b["chyby"][0]
    # jen jeden pokus na zdroj (bez opakování) a pokus je v raw.stazeni u běhu
    assert len(s.dotazy) == 4
    pokusy = conn.execute("SELECT count(*) AS n FROM raw.stazeni WHERE beh_id IS NOT NULL AND http_status IS NULL")
    assert pokusy.fetchone()["n"] == 4


def test_chyba_zdroje_se_zapise_a_beh_nespadne(conn, tmp_path):
    def spadni(_beh):
        raise ValueError("neočekávaný formát")

    s = FalesnyStahovac(conn, tmp_path, {"https://example.invalid/": b"ok"})
    beh_id, stav = spust(conn, s, Sberac("vvz", "https://example.invalid/", spadni, "test"), OD, DO)
    b = _beh(conn, beh_id)
    assert stav == b["stav"] == "chyba" and "neočekávaný formát" in b["chyby"][0]


def test_evidence_behu_je_pouze_pro_insert(conn, tmp_path):
    beh_id, _ = spust(conn, FalesnyStahovac(conn, tmp_path, {}), sberace.SBERACE["nen"], OD, DO)
    for sql in ("UPDATE raw.beh SET zdroj = 'vvz'", "DELETE FROM raw.beh_konec", "UPDATE raw.beh_konec SET stav = 'uspech'"):
        with pytest.raises(psycopg.Error) as e:
            conn.execute(sql)
        assert e.value.sqlstate == "PV001"
        conn.rollback()
    with pytest.raises(psycopg.errors.UniqueViolation):  # běh nelze ukončit dvakrát
        conn.execute("INSERT INTO raw.beh_konec (beh_id, stav) VALUES (%s, 'uspech')", (beh_id,))
    conn.rollback()


def _vvz_data():
    filtry = {
        "formGroup": "vz", "form": "vz", "workflowPlace": "UVEREJNENO_VVZ",
        "data.datumUverejneniVvz[gte]": OD.isoformat(), "data.datumUverejneniVvz[lt]": DO.isoformat(),
        "order[variableId]": "asc",
    }
    polozka = lambda i: {  # noqa: E731
        "id": f"uuid-{i}", "variableId": f"F2026-00000{i}", "dataHash": f"h{i}",
        "owner": {"name": "Jana Nováková", "email": "jana@example.invalid"},
        "createdBy": {"name": "Jana Nováková"}, "updatedBy": {"name": "most"},
        "data": {"zadavatele": [{"ico": "00064581", "nazev": "Obec"}], "zdrojPodani": {"typ": "WEB", "uzivatelVvzLogin": "jnovak"}},
    }
    api = f"{vvz.API}/api/submissions/search"
    return {
        sberace.SBERACE["vvz"].url_dostupnosti: b"[]",
        _url(api, **filtry, page=1, limit=250): (json.dumps([polozka(1), polozka(2)]).encode(),
                                                 {"x-total-count": "3", "x-last-page": "2"}),
        _url(api, **filtry, page=2, limit=250): (json.dumps([polozka(3)]).encode(), {"x-total-count": "3"}),
    }, polozka(1)


def test_vvz_pocet_ze_zdroje_puvod_a_opakovany_beh_bez_duplicit(conn, tmp_path):
    data, prvni = _vvz_data()
    s = FalesnyStahovac(conn, tmp_path, data)
    beh1, stav = spust(conn, s, sberace.SBERACE["vvz"], OD, DO)
    b = _beh(conn, beh1)
    assert stav == "uspech" and (b["pocet_zaznamu"], b["pocet_novych"], b["pocet_ve_zdroji"]) == (3, 3, 3)
    beh2, stav2 = spust(conn, s, sberace.SBERACE["vvz"], OD, DO)
    b2 = _beh(conn, beh2)
    assert stav2 == "uspech" and (b2["pocet_zaznamu"], b2["pocet_novych"]) == (3, 0)
    zaznamy = _zaznamy(conn, "vvz")
    assert [z["id_ve_zdroji"] for z in zaznamy] == ["F2026-000001", "F2026-000002", "F2026-000003"]
    z = zaznamy[0]
    # původ: zdroj, ID ve zdroji, URL, čas stažení, hash původního záznamu, stažení a běh
    assert z["hash"] == raw.hash_zaznamu(prvni) and z["beh_id"] == beh1 and "page=1" in z["url"]
    assert conn.execute("SELECT beh_id FROM raw.stazeni WHERE id = %s", (z["stazeni_id"],)).fetchone()["beh_id"] == beh1
    # osoby zadávající formulář se neukládají
    assert "owner" not in z["obsah"] and "uzivatelVvzLogin" not in z["obsah"]["data"]["zdrojPodani"]
    assert {"owner", "createdBy", "updatedBy", "data.zdrojPodani.uzivatelVvzLogin"} <= set(z["redigovano"])


def test_registr_smluv_z_dennich_dumpu(conn, tmp_path):
    den = date(2026, 9, 1)
    s = FalesnyStahovac(conn, tmp_path, {
        f"{rs.DATA_URL}/index.xml": b"<index/>",
        f"{rs.DATA_URL}/dump_{den:%Y_%m_%d}.xml": DUMP.read_bytes(),
    })
    beh_id, stav = spust(conn, s, sberace.SBERACE["registr_smluv"], den, date(2026, 9, 3))
    b = _beh(conn, beh_id)
    # chybějící denní dump (2. 9.) je chyba běhu, záznamy z dostupného dne se uloží
    assert stav == "chyba" and b["pocet_zaznamu"] == 2 and "dump_2026_09_02" in b["chyby"][0]
    zaznamy = {z["id_ve_zdroji"]: z for z in _zaznamy(conn, "registr_smluv")}
    assert len(zaznamy) == 2
    fo = next(z for z in zaznamy.values() if z["redigovano"])
    strana = fo["obsah"]["smlouva"]["smluvniStrana"]
    assert "nazev" not in strana and strana["prijemce"] == "true"  # strana bez IČO bez názvu (D-009)
    firma = next(z for z in zaznamy.values() if z["id_ve_zdroji"] == "39673953")
    assert firma["obsah"]["smlouva"]["smluvniStrana"]["nazev"] == "Stavby Příklad s.r.o."
    spust(conn, s, sberace.SBERACE["registr_smluv"], den, date(2026, 9, 2))
    assert len(_zaznamy(conn, "registr_smluv")) == 2


def test_isvz_mesicni_soubory_ze_stranky_otevrenych_dat(conn, tmp_path):
    stranka = (b'<a href="/files/rvz_2026-07.json">cervenec</a><a href="/files/rvz_2026-08.json">srpen</a>'
               b'<a href="https://isvz.nipez.cz/files/rvz_2026-09.zip">zari</a>')
    srpen = json.dumps({"zakazky": [{"id": "Z1", "nazev": "Oprava", "kontaktniOsoba": "Petr", "dodavatel": {"nazev": "Jan Novák"}},
                                    {"id": "Z2", "dodavatel": {"nazev": "Firma a.s.", "ico": "12345678"}}]}).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("rvz_2026-09.xml", "<data><zakazka><id>Z3</id><email>a@b.cz</email></zakazka>"
                                      "<zakazka><id>Z4</id></zakazka></data>")
    s = FalesnyStahovac(conn, tmp_path, {
        sberace.ISVZ_OPENDATA: stranka,
        "https://isvz.nipez.cz/files/rvz_2026-08.json": srpen,
        "https://isvz.nipez.cz/files/rvz_2026-09.zip": buf.getvalue(),
    })
    beh_id, stav = spust(conn, s, sberace.SBERACE["isvz"], OD, DO)
    assert stav == "uspech" and _beh(conn, beh_id)["pocet_zaznamu"] == 4
    assert not any("2026-07" in d for d in s.dotazy)
    z = {r["id_ve_zdroji"]: r for r in _zaznamy(conn, "isvz")}
    assert set(z) == {"Z1", "Z2", "Z3", "Z4"}
    assert "kontaktniOsoba" not in z["Z1"]["obsah"] and "nazev" not in z["Z1"]["obsah"]["dodavatel"]
    assert z["Z2"]["obsah"]["dodavatel"]["nazev"] == "Firma a.s." and "email" not in z["Z3"]["obsah"]


def test_nen_xml_data_profilu(conn, tmp_path):
    seznam = b'<a href="/profil/MVCR">MV</a><a href="/profily-zadavatelu-platne?page=2">dalsi</a>'
    seznam2 = b'<a href="/profil/DIA">DIA</a>'
    xml = ('<profil><zakazka><VZ><kod_vz_na_profilu>N006/26/V1</kod_vz_na_profilu></VZ>'
           '<dodavatel><nazev_dodavatele>Jan Novák</nazev_dodavatele><ico_dodavatele></ico_dodavatele></dodavatel>'
           '</zakazka></profil>').encode()
    parametry = {"od": "26082026", "do": "25092026"}
    s = FalesnyStahovac(conn, tmp_path, {
        sberace.NEN_PROFILY: seznam,
        f"{sberace.NEN_PROFILY}?page=2": seznam2,
        _url(f"{sberace.NEN_WEB}/profil/MVCR/XMLdataVZ", **parametry): xml,
        _url(f"{sberace.NEN_WEB}/profil/DIA/XMLdataVZ", **parametry): b"<profil/>",
    })
    beh_id, stav = spust(conn, s, sberace.SBERACE["nen"], OD, DO)
    assert stav == "uspech" and _beh(conn, beh_id)["pocet_zaznamu"] == 1
    (z,) = _zaznamy(conn, "nen")
    assert z["id_ve_zdroji"] == "MVCR/N006/26/V1"
    assert "nazev_dodavatele" not in z["obsah"]["dodavatel"] and z["redigovano"] == ["dodavatel.nazev_dodavatele"]


def _red_data(tmp_path):
    iri = "https://data.mf.gov.cz/red/"
    dotace = [
        {"iriDotace": f"{iri}dotace/1", "iriPrijemce": f"{iri}prijemce/1", "podpisDatum": "2026-02-10", "datumExportu": "2026-02-21"},
        {"iriDotace": f"{iri}dotace/2", "iriPrijemce": f"{iri}prijemce/2", "podpisDatum": "2025-06-01", "datumExportu": "2026-02-21"},
    ]
    prijemci = [
        {"iriPrijemce": f"{iri}prijemce/1", "ico": "", "jmeno": "Jan", "prijmeni": "Novák", "rokNarozeni": "1970"},
        {"iriPrijemce": f"{iri}prijemce/2", "ico": "12345678", "jmeno": "", "prijmeni": "", "rokNarozeni": ""},
    ]
    rozhodnuti = [{"iriRozhodnuti": f"{iri}rozhodnuti/1", "iriDotace": f"{iri}dotace/1", "castkaRozhodnuta": "1000"}]
    data = {sberace.SBERACE["red"].url_dostupnosti: b"{}"}
    for tabulka, balicek, radky in (("dotace", "dotace", dotace), ("prijemce", "prijemce-pomoci", prijemci),
                                     ("rozhodnuti", "rozhodnuti", rozhodnuti)):
        url = f"https://red.fs.gov.cz/opendata/{tabulka}.csv.gz"
        katalog = {"result": {"resources": [{"url": url.replace("red.fs.gov.cz", "red.financnisprava.cz"),
                                             "last_modified": "2026-03-24"}]}}
        data[_url(dotace_zdroje.RED_CKAN, id=balicek)] = json.dumps(katalog).encode()
        data[url] = _gz_csv(radky)
    return data


def test_red_okno_podle_exportu_prijemci_a_rozhodnuti(conn, tmp_path):
    s = FalesnyStahovac(conn, tmp_path, _red_data(tmp_path))
    beh_id, stav = spust(conn, s, sberace.SBERACE["red"], OD, DO)
    b = _beh(conn, beh_id)
    # export 21. 2. 2026 je starší než období -> měsíční okno končící exportem (D-022)
    assert stav == "uspech" and b["pocet_zaznamu"] == 3 and "okno_podle_exportu" in b["poznamka"]
    z = {r["id_ve_zdroji"].rsplit("/", 2)[-2]: r for r in _zaznamy(conn, "red")}
    assert set(z) == {"dotace", "prijemce", "rozhodnuti"}
    assert "jmeno" not in z["prijemce"]["obsah"] and set(z["prijemce"]["redigovano"]) == {"jmeno", "prijmeni", "rokNarozeni"}
    spust(conn, s, sberace.SBERACE["red"], OD, DO)
    assert len(_zaznamy(conn, "red")) == 3


def test_cedr_soubory_podle_konvence(conn, tmp_path):
    zaklad = "https://cedropendata.mfcr.cz/c3lod"
    s = FalesnyStahovac(conn, tmp_path, {
        sberace.CEDR_INDEX: b"<html>CEDR</html>",
        f"{zaklad}/Dotace.csv.gz": _gz_csv([{"idDotace": "D1", "idPrijemce": "P1", "podpisDatum": "2026-09-01"},
                                             {"idDotace": "D2", "idPrijemce": "P2", "podpisDatum": "2020-01-01"}]),
        f"{zaklad}/PrijemcePomoci.csv.gz": _gz_csv([{"idPrijemce": "P1", "ico": "12345678", "jmeno": ""}]),
        f"{zaklad}/Rozhodnuti.csv.gz": _gz_csv([{"idRozhodnuti": "R1", "idDotace": "D1", "castkaRozhodnuta": "5"}]),
    })
    beh_id, stav = spust(conn, s, sberace.SBERACE["cedr"], OD, DO)
    assert stav == "uspech" and _beh(conn, beh_id)["pocet_zaznamu"] == 3
    assert [r["id_ve_zdroji"] for r in _zaznamy(conn, "cedr")] == ["D1", "P1", "R1"]


def test_seznam_operaci_xlsx(conn, tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["00-034 Seznam operací (List of Operations) 2021-2027"])
    ws.append([])
    hlavicka = ["Registrační číslo projektu", "Příjemce - název", "IČ příjemce", "Právní forma příjemce", "PSČ příjemce",
                "Číslo řádku", "Název dodavatele veřejné zakázky", "IČ dodavatele veřejné zakázky", "Poddodavatel"]
    ws.append(hlavicka)
    ws.append(["Project registration number", "Beneficiary name", "", "", "", "", "", "", ""])
    ws.append(["CZ.01/001", "Obec Příklad", "00012345", "Obec", "11000", 1, "Stavby s.r.o.", "45023522", None])
    ws.append(["CZ.01/001", "Obec Příklad", "00012345", "Obec", "11000", 2, "Jan Novák", None, "Petr Svoboda"])
    ws.append(["CZ.01/002", "Jana Nová", None, "Fyzická osoba podnikající", "37001", None, None, None, None])
    xlsx = io.BytesIO()
    wb.save(xlsx)
    soubor = "/getmedia/abc/2026_09_Seznam-operaci_List-of-Operations_21.xlsx.aspx?ext=.xlsx"
    stranka = f'<a href="{soubor}">Seznam operací 21+ (List of Operations) 01/09/2026</a>'.encode()
    s = FalesnyStahovac(conn, tmp_path, {dotace_zdroje.EU_STRANKA: stranka, f"https://www.dotaceeu.cz{soubor}": xlsx.getvalue()})
    beh_id, stav = spust(conn, s, sberace.SBERACE["dotaceeu_2127"], OD, DO)
    assert stav == "uspech" and _beh(conn, beh_id)["pocet_zaznamu"] == 3
    z = {r["id_ve_zdroji"]: r for r in _zaznamy(conn, "dotaceeu_2127")}
    assert set(z) == {"CZ.01/001#1", "CZ.01/001#2", "CZ.01/002"}
    assert z["CZ.01/001#1"]["obsah"]["Název dodavatele veřejné zakázky"] == "Stavby s.r.o."
    assert set(z["CZ.01/001#2"]["redigovano"]) == {"Název dodavatele veřejné zakázky", "Poddodavatel"}
    assert set(z["CZ.01/002"]["redigovano"]) == {"Příjemce - název", "PSČ příjemce"}


def test_rediguj_hash_z_puvodniho_zaznamu():
    puvodni = {"strana": [{"nazev": "Jan Novák", "adresa": "X"}, {"nazev": "Firma", "ico": "12345678"}], "email": "a@b"}
    ulozeny, cesty = sberace.rediguj(puvodni, frozenset({"strana"}))
    assert ulozeny == {"strana": [{}, {"nazev": "Firma", "ico": "12345678"}]}
    assert cesty == ["strana[0].nazev", "strana[0].adresa", "email"]
    assert puvodni["email"] == "a@b"  # původní záznam (pro hash) zůstává úplný


def test_vychozi_obdobi_je_posledni_mesic(monkeypatch):
    monkeypatch.delenv("PVK_SBER_OD", raising=False)
    monkeypatch.delenv("PVK_SBER_DO", raising=False)
    assert cli.vychozi_obdobi(date(2026, 9, 26)) == (date(2026, 8, 26), date(2026, 9, 26))
    assert cli.vychozi_obdobi(date(2026, 3, 31)) == (date(2026, 2, 28), date(2026, 3, 31))
    assert cli.mesic_zpet(date(2026, 1, 15)) == date(2025, 12, 15)


def test_prikaz_stav_a_neznamy_zdroj(conn, tmp_path, test_db_url, monkeypatch, capsys):
    spust(conn, FalesnyStahovac(conn, tmp_path, {}), sberace.SBERACE["isvz"], OD, DO)
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    assert cli.main(["stav"]) == 0
    vystup = capsys.readouterr().out
    assert "isvz" in vystup and "preskoceno" in vystup
    assert cli.main(["sber", "--zdroje", "neexistuje"]) == 2
    assert list(sberace.SBERACE) == ["registr_smluv", "vvz", "isvz", "nen", "red", "cedr", "dotaceeu_2127"]
