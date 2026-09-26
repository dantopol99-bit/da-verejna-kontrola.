"""PODMÍNKY NEPUBLIKOVÁNÍ – musí shodit build.

1. Jednotkové testy: brána (pvk.publikace) zachytí každou podmínku a propustí bezvadný výstup.
2. Test výstupů repozitáře: nad skutečnými výstupy (vystupy/, docs/pilot_report.md,
   docs/pilot_vyjimky.csv) nesmí brána najít žádné porušení – jinak test selže a s ním build.
3. Databáze: struktura ind/core podmínky vynucuje sama (NOT NULL, jeden typ částky, pohledy).
"""

from __future__ import annotations

import json
import shutil

import psycopg
import pytest

from pvk import publikace
from pvk.config import KOREN
from pvk.core import zajisti_metodiku

METODIKA = {"min_pocet_pripadu": 30, "min_zaklad": None}

DOBRY_INDIKATOR = {
    "druh": "indikator",
    "indikator_kod": "podil_zakazek_bez_souteze",
    "obdobi_od": "2025-01-01",
    "obdobi_do": "2026-01-01",
    "pocet_pripadu": 42,
    "metodika_verze": "pilot-2026.09",
    "text": "Signál k prověření: 12 ze 42 zakázek bylo zadáno bez uveřejnění.",
}


def kody(poruseni):
    return sorted({p.kod for p in poruseni})


# --- indikátor -----------------------------------------------------------------------------------


def test_bezvadny_indikator_projde():
    assert publikace.over_indikator(DOBRY_INDIKATOR, METODIKA) == []


@pytest.mark.parametrize(
    ("zmena", "kod"),
    [
        ({"obdobi_od": None}, "INDIKATOR_BEZ_OBDOBI"),
        ({"obdobi_do": ""}, "INDIKATOR_BEZ_OBDOBI"),
        ({"pocet_pripadu": None}, "INDIKATOR_BEZ_POCTU_PRIPADU"),
        ({"metodika_verze": None}, "INDIKATOR_BEZ_VERZE_METODIKY"),
        ({"pocet_pripadu": 29}, "INDIKATOR_POD_MINIMALNIM_ZAKLADEM"),
        ({"pocet_pripadu": 0}, "INDIKATOR_POD_MINIMALNIM_ZAKLADEM"),
    ],
)
def test_indikator_nepublikovat(zmena, kod):
    assert kod in kody(publikace.over_indikator({**DOBRY_INDIKATOR, **zmena}, METODIKA))


def test_indikator_s_neznamou_verzi_metodiky():
    assert "INDIKATOR_BEZ_VERZE_METODIKY" in kody(publikace.over_indikator(DOBRY_INDIKATOR, None))


def test_indikator_pod_minimalnim_zakladem_objemu():
    p = publikace.over_indikator({**DOBRY_INDIKATOR, "zaklad": 10}, {"min_pocet_pripadu": 30, "min_zaklad": 100})
    assert "INDIKATOR_POD_MINIMALNIM_ZAKLADEM" in kody(p)


def test_indikator_bez_minima_v_metodice_se_nepublikuje():
    assert "INDIKATOR_POD_MINIMALNIM_ZAKLADEM" in kody(publikace.over_indikator(DOBRY_INDIKATOR, {}))


# --- částky a souhrny ------------------------------------------------------------------------------

CASTKA = {"typ": "smluvni", "mena": "CZK", "dph_rezim": "bez_dph", "perioda": "celkem", "hodnota": "100"}


def test_castka_s_typem_projde():
    assert publikace.over_castku(CASTKA) == []


@pytest.mark.parametrize("pole", ["typ", "mena", "dph_rezim", "perioda"])
def test_castka_bez_typu(pole):
    assert kody(publikace.over_castku({**CASTKA, pole: None})) == ["CASTKA_BEZ_TYPU"]


def test_souhrn_jednoho_typu_projde():
    s = {"castky": [CASTKA, {**CASTKA, "hodnota": "5"}], "podil_heuristicke_deduplikace": 0.12}
    assert publikace.over_souhrn(s) == []


@pytest.mark.parametrize(
    "jina",
    [
        {**CASTKA, "typ": "vysoutezena"},
        {**CASTKA, "typ": "dotace_priznana"},
        {**CASTKA, "mena": "EUR"},
        {**CASTKA, "dph_rezim": "vcetne_dph"},
        {**CASTKA, "perioda": "rocni"},
    ],
)
def test_souhrn_scitajici_ruzne_typy(jina):
    s = {"castky": [CASTKA, jina], "podil_heuristicke_deduplikace": 0.0}
    assert "SOUHRN_RUZNYCH_TYPU" in kody(publikace.over_souhrn(s))


def test_souhrn_s_castkou_bez_typu():
    s = {"castky": [CASTKA, {**CASTKA, "typ": None}], "podil_heuristicke_deduplikace": 0.0}
    assert "CASTKA_BEZ_TYPU" in kody(publikace.over_souhrn(s))


@pytest.mark.parametrize("podil", [None, -0.1, 1.5])
def test_souhrn_bez_podilu_heuristicke_deduplikace(podil):
    s = {"castky": [CASTKA], "podil_heuristicke_deduplikace": podil}
    assert "SOUHRN_BEZ_PODILU_HEURISTIKY" in kody(publikace.over_souhrn(s))


# --- hodnotící slova -------------------------------------------------------------------------------

HODNOTICI = [
    "podezřelý dodavatel",
    "Podezřelá zakázka",
    "PODEZŘENÍ na předražení",
    "podezrely",
    "je to rizikový dodavatel",
    "rizikového dodavatele",
    "Rizikoví dodavatelé",
    "rizikovy\ndodavatel",
    "firma propojená s radním",
    "propojen se starostou",
    "jsou propojeni s",
    "subjekt napojený na politika",
    "napojen na",
    "napojená na",
    "napojeni na",
]
NEUTRALNI = [
    "Smlouva o dílo",
    "riziko prodlení",
    "rizikové faktory projektu",
    "propojení sítí",
    "napojení na kanalizaci",
    "Stavba zahrnuje napojením na vodovod",
    "propojení s rozvodnou sítí",
    "dodavatel stavby",
    "",
]


@pytest.mark.parametrize("text", HODNOTICI)
def test_hodnotici_slova_se_nepublikuji(text):
    assert kody(publikace.over_text(text)) == ["HODNOTICI_SLOVA"]


@pytest.mark.parametrize("text", NEUTRALNI)
def test_neutralni_text_projde(text):
    assert publikace.over_text(text) == []


def test_hodnotici_slova_v_textu_indikatoru():
    p = publikace.over_indikator({**DOBRY_INDIKATOR, "text": "Rizikový dodavatel s 42 zakázkami"}, METODIKA)
    assert kody(p) == ["HODNOTICI_SLOVA"]


# --- profily ---------------------------------------------------------------------------------------


def test_profil_pravnicke_osoby_projde():
    assert publikace.over_profil({"druh": "profil", "ico": "00255513", "je_fyzicka_osoba": False}) == []


@pytest.mark.parametrize("fo", [True, None])
def test_profil_fyzicke_osoby_se_nepublikuje(fo):
    assert "PROFIL_FYZICKE_OSOBY" in kody(publikace.over_profil({"druh": "profil", "je_fyzicka_osoba": fo}))


# --- brána nad výstupy (build) ---------------------------------------------------------------------


def test_vystupy_repozitare_splnuji_publikacni_podminky():
    """Build gate: jakékoli porušení ve skutečných výstupech repozitáře shodí build."""
    poruseni = publikace.over_vystupy(KOREN)
    assert poruseni == [], "\n".join(map(str, poruseni))


def _repo_s_vystupem(tmp_path, vystup) -> int:
    (tmp_path / "metodika").mkdir()
    shutil.copy(KOREN / "metodika" / "pilot-2026.09.json", tmp_path / "metodika")
    (tmp_path / "vystupy").mkdir()
    (tmp_path / "vystupy" / "vystup.json").write_text(json.dumps(vystup, ensure_ascii=False), encoding="utf-8")
    return publikace.main([str(tmp_path)])


def test_brana_propusti_bezvadne_vystupy(tmp_path):
    assert _repo_s_vystupem(tmp_path, [DOBRY_INDIKATOR]) == 0


@pytest.mark.parametrize(
    "spatny",
    [
        {**DOBRY_INDIKATOR, "obdobi_od": None},
        {**DOBRY_INDIKATOR, "pocet_pripadu": None},
        {**DOBRY_INDIKATOR, "metodika_verze": None},
        {**DOBRY_INDIKATOR, "pocet_pripadu": 3},
        {**DOBRY_INDIKATOR, "text": "Dodavatel napojený na radnici"},
        {"druh": "castka", **{**CASTKA, "typ": None}},
        {"druh": "souhrn", "castky": [CASTKA, {**CASTKA, "typ": "vysoutezena"}], "podil_heuristicke_deduplikace": 0},
        {"druh": "souhrn", "castky": [CASTKA]},
        {"druh": "profil", "je_fyzicka_osoba": True},
        {"druh": "neco_jineho"},
    ],
)
def test_brana_shodi_build_pri_spatnem_vystupu(tmp_path, spatny):
    assert _repo_s_vystupem(tmp_path, [DOBRY_INDIKATOR, spatny]) == 1


def test_brana_kontroluje_i_textove_vystupy(tmp_path):
    (tmp_path / "vystupy").mkdir()
    (tmp_path / "vystupy" / "clanek.md").write_text("Podezřelý tender", encoding="utf-8")
    assert publikace.main([str(tmp_path)]) == 1


# --- databáze --------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", HODNOTICI + NEUTRALNI)
def test_sql_a_python_vzory_se_shoduji(db, text):
    sql = db.execute("SELECT ind.obsahuje_hodnotici_slova(%s) AS h", (text,)).fetchone()["h"]
    assert sql == bool(publikace.najdi_hodnotici_slova(text))


@pytest.fixture
def metodika_id(db):
    klic = zajisti_metodiku(
        db,
        {
            "kod": "test-publikace",
            "popis": "test",
            "platnost_od": "2020-01-01",
            "parametry": {"min_pocet_pripadu": 30},
        },
    )
    db.commit()
    return klic


@pytest.mark.parametrize(
    ("sloupec", "hodnota"),
    [("obdobi_od", None), ("obdobi_do", None), ("pocet_pripadu", None), ("metodika_verze_id", None)],
)
def test_db_indikator_bez_povinnych_udaju_nelze_ulozit(db, metodika_id, sloupec, hodnota):
    radek = {
        "indikator_kod": "test",
        "obdobi_od": "2025-01-01",
        "obdobi_do": "2026-01-01",
        "pocet_pripadu": 40,
        "metodika_verze_id": metodika_id,
    }
    radek[sloupec] = hodnota
    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute(
            "INSERT INTO ind.indikator_vysledek (indikator_kod, obdobi_od, obdobi_do, pocet_pripadu, metodika_verze_id, "
            "zaklad, srovnavaci_skupina) VALUES (%(indikator_kod)s, %(obdobi_od)s, %(obdobi_do)s, %(pocet_pripadu)s, "
            "%(metodika_verze_id)s, 40, 'test')",
            radek,
        )


def test_db_k_publikaci_jen_nad_minimem_a_bez_hodnoticich_slov(db, metodika_id):
    for kod, pocet, text in [
        ("nad_minimem", 30, "Signál k prověření."),
        ("pod_minimem", 29, "Signál k prověření."),
        ("hodnotici", 50, "Podezřelý dodavatel."),
    ]:
        db.execute(
            "INSERT INTO ind.indikator_vysledek (indikator_kod, obdobi_od, obdobi_do, pocet_pripadu, "
            "metodika_verze_id, text, zaklad, srovnavaci_skupina) VALUES (%s, '2025-01-01', '2026-01-01', %s, %s, %s, 40, 't')",
            (kod, pocet, metodika_id, text),
        )
    publikovatelne = {
        r["indikator_kod"]
        for r in db.execute(
            "SELECT indikator_kod FROM ind.indikator_k_publikaci WHERE metodika_verze_id = %s", (metodika_id,)
        )
    }
    assert publikovatelne == {"nad_minimem"}


def test_db_souhrn_bez_podilu_heuristiky_nelze_ulozit(db, metodika_id):
    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute(
            "INSERT INTO ind.souhrn (kod, obdobi_od, obdobi_do, castka, pocet_castek, metodika_verze_id) "
            "VALUES ('test', '2025-01-01', '2026-01-01', ROW('smluvni','CZK','bez_dph','celkem',1), 1, %s)",
            (metodika_id,),
        )


def test_db_souhrn_bez_typu_castky_nelze_ulozit(db, metodika_id):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO ind.souhrn (kod, obdobi_od, obdobi_do, castka, pocet_castek, "
            "podil_heuristicke_deduplikace, metodika_verze_id) "
            "VALUES ('test', '2025-01-01', '2026-01-01', ROW(NULL,'CZK','bez_dph','celkem',1), 1, 0, %s)",
            (metodika_id,),
        )


def test_db_souhrn_ruznych_typu_nevznikne(db, metodika_id):
    with pytest.raises(psycopg.Error):
        db.execute(
            "INSERT INTO ind.souhrn (kod, obdobi_od, obdobi_do, castka, pocet_castek, "
            "podil_heuristicke_deduplikace, metodika_verze_id) "
            "SELECT 'test', '2025-01-01', '2026-01-01', core.soucet(x), count(*), 0, %s FROM (VALUES "
            "(ROW('smluvni','CZK','bez_dph','celkem',1)::core.typovana_castka), "
            "(ROW('dotace_priznana','CZK','mimo_dph','celkem',1)::core.typovana_castka)) v(x)",
            (metodika_id,),
        )


def test_db_ind_je_pouze_pro_insert(db, metodika_id):
    db.execute(
        "INSERT INTO ind.indikator_vysledek (indikator_kod, obdobi_od, obdobi_do, pocet_pripadu, metodika_verze_id, "
        "zaklad, srovnavaci_skupina) VALUES ('x', '2025-01-01', '2026-01-01', 40, %s, 40, 't')",
        (metodika_id,),
    )
    with pytest.raises(psycopg.Error) as e:
        db.execute("UPDATE ind.indikator_vysledek SET pocet_pripadu = 1")
    assert e.value.sqlstate == "PV001"


def test_db_min_zaklad_null_znamena_bez_minima_objemu(db):
    klic = zajisti_metodiku(db, {"kod": "test-min-zaklad-null", "popis": "test", "platnost_od": "2020-01-01",
                                 "parametry": {"min_pocet_pripadu": 30, "min_zaklad": None}})
    db.commit()
    db.execute(
        "INSERT INTO ind.indikator_vysledek (indikator_kod, obdobi_od, obdobi_do, pocet_pripadu, zaklad, "
        "metodika_verze_id, srovnavaci_skupina) VALUES ('se_zakladem', '2025-01-01', '2026-01-01', 40, 1, %s, 't')",
        (klic,),
    )
    assert db.execute(
        "SELECT count(*) AS n FROM ind.indikator_k_publikaci WHERE metodika_verze_id = %s", (klic,)
    ).fetchone()["n"] == 1


# --- D-039: dotační údaj nese stav k datu; D-040: vývojový vzorek se nepublikuje ------------------

DOTACE = {"typ": "dotace_priznana", "mena": "CZK", "dph_rezim": "mimo_dph", "perioda": "celkem", "hodnota": "100"}


@pytest.mark.parametrize(
    "vystup",
    [
        {"druh": "castka", **DOTACE},
        {"druh": "castka", **DOTACE, "stav_k_datu": ""},
        {"druh": "castka", **DOTACE, "stav_k_datu": "nevime"},
        {"druh": "castka", **{**DOTACE, "typ": "dotace_cerpana"}},
        {"druh": "castka", **{**DOTACE, "typ": "vratka"}},
        {"druh": "castka", **CASTKA, "zdroj": "red"},
        {"druh": "souhrn", "castky": [DOTACE], "podil_heuristicke_deduplikace": 0},
        {**DOBRY_INDIKATOR, "typ_castky": "dotace_priznana"},
        {**DOBRY_INDIKATOR, "zdroj": "dotaceeu_2127"},
    ],
)
def test_dotacni_udaj_bez_stavu_k_datu_neprojde(vystup):
    p = publikace.over_vystup(vystup, {"pilot-2026.09": METODIKA}, "test")
    assert "DOTACE_BEZ_STAVU_K_DATU" in kody(p)


@pytest.mark.parametrize(
    "vystup",
    [
        {"druh": "castka", **DOTACE, "stav_k_datu": "2026-02-21"},
        {"druh": "souhrn", "castky": [DOTACE], "podil_heuristicke_deduplikace": 0, "stav_k_datu": "2026-02-21"},
        {**DOBRY_INDIKATOR, "typ_castky": "dotace_priznana", "stav_k_datu": "2026-02-21"},
        {"druh": "castka", **CASTKA},  # nedotační částka stav k datu nepotřebuje
    ],
)
def test_dotacni_udaj_se_stavem_k_datu_projde(vystup):
    assert publikace.over_vystup(vystup, {"pilot-2026.09": METODIKA}, "test") == []


def test_brana_shodi_build_pri_dotaci_bez_stavu_k_datu(tmp_path):
    assert _repo_s_vystupem(tmp_path, [DOBRY_INDIKATOR, {"druh": "castka", **DOTACE}]) == 1
    (tmp_path / "b").mkdir()
    assert _repo_s_vystupem(tmp_path / "b", [{"druh": "castka", **DOTACE, "stav_k_datu": "2026-02-21"}]) == 0


@pytest.mark.parametrize(
    "vystup",
    [{"druh": "castka", **CASTKA, "zdroj": "hlidac_statu_rs"}, {"druh": "castka", **CASTKA, "vyvojovy_vzorek": True},
     {**DOBRY_INDIKATOR, "vyvojovy_vzorek": True}],
)
def test_vyvojovy_vzorek_se_nepublikuje(vystup):
    assert "VYVOJOVY_VZOREK" in kody(publikace.over_vystup(vystup, {"pilot-2026.09": METODIKA}, "test"))


def test_db_dotacni_vysledek_bez_stavu_dat_se_nepublikuje(db, metodika_id):
    for kod, typ, stav in [("dotace_bez_stavu", "dotace_priznana", None), ("dotace_se_stavem", "dotace_priznana",
                           "2026-02-21"), ("smlouvy", "smluvni", None)]:
        db.execute(
            "INSERT INTO ind.indikator_vysledek (indikator_kod, obdobi_od, obdobi_do, pocet_pripadu, typ_castky, "
            "stav_dat_k, metodika_verze_id, zaklad, srovnavaci_skupina) VALUES (%s, '2025-01-01', '2026-01-01', 40, %s, %s, %s, 40, 't')",
            (kod, typ, stav, metodika_id),
        )
    publikovatelne = {r["indikator_kod"] for r in db.execute(
        "SELECT indikator_kod FROM ind.indikator_k_publikaci WHERE metodika_verze_id = %s", (metodika_id,))}
    assert publikovatelne == {"dotace_se_stavem", "smlouvy"}
    for stav in (None, "2026-02-21"):
        db.execute(
            "INSERT INTO ind.souhrn (kod, obdobi_od, obdobi_do, castka, pocet_castek, podil_heuristicke_deduplikace, "
            "metodika_verze_id, stav_dat_k) VALUES ('dotace', '2025-01-01', '2026-01-01', "
            "ROW('dotace_priznana','CZK','mimo_dph','celkem',1), 1, 0, %s, %s)",
            (metodika_id, stav),
        )
    assert db.execute("SELECT count(*) AS n FROM ind.souhrn_k_publikaci WHERE metodika_verze_id = %s",
                      (metodika_id,)).fetchone()["n"] == 1


# --- D-046: souhrn s podílem heuristiky, nad prahem s rozpětím --------------------------------------

SOUHRN_SUBJEKTU = {"druh": "souhrn", **CASTKA, "metodika_verze": "souhrny-2026.09", "podil_heuristicke_deduplikace": 0.2,
                   "rozpeti": {"dolni_se_shodou": "80", "horni_bez_shody": "100"}}


@pytest.mark.parametrize(
    ("zmena", "kod"),
    [
        ({"podil_heuristicke_deduplikace": None}, "SOUHRN_BEZ_PODILU_HEURISTIKY"),
        ({"rozpeti": None}, "SOUHRN_BEZ_ROZPETI"),
        ({"rozpeti": {"dolni_se_shodou": "80"}}, "SOUHRN_BEZ_ROZPETI"),
    ],
)
def test_souhrn_subjektu_bez_podilu_nebo_rozpeti_neprojde(tmp_path, zmena, kod):
    metodiky = publikace.nacti_metodiky()
    metodiky["parovani-2026.09"] = {**metodiky["parovani-2026.09"], "overeno": True}  # jen pravidla D-046
    assert publikace.over_vystup(SOUHRN_SUBJEKTU, metodiky, "test") == []
    assert kod in kody(publikace.over_vystup({**SOUHRN_SUBJEKTU, **zmena}, metodiky, "test"))


# --- D-049: párování smlouva–zakázka nesmí do výstupu, dokud není ověřené ------------------------

@pytest.mark.parametrize(
    "vystup",
    [
        {"druh": "text", "text": "Případ ke kontrole", "parovani": [{"id_verze": "1", "skore": 0.8}]},
        {"druh": "text", "text": "Shoda", "metoda": "heuristika_ico_datum_castka_predmet"},
        {"druh": "text", "text": "Shoda", "metoda": "odkaz_bt151"},
        {**DOBRY_INDIKATOR, "metodika_verze": "parovani-2026.09"},
        {**SOUHRN_SUBJEKTU},  # souhrn s podílem heuristické deduplikace > 0 stojí na párování
    ],
)
def test_parovani_neprojde_dokud_neni_overene(vystup):
    metodiky = publikace.nacti_metodiky()
    assert publikace.parovani_overeno(metodiky) is False
    assert "PAROVANI_NEOVERENE" in kody(publikace.over_vystup(vystup, metodiky, "test"))


def test_parovani_projde_az_po_overeni_metodiky():
    metodiky = {**publikace.nacti_metodiky()}
    metodiky["parovani-2026.09"] = {**metodiky["parovani-2026.09"], "overeno": True}
    assert publikace.over_vystup({"druh": "text", "text": "Shoda", "metoda": "odkaz_bt151"}, metodiky, "t") == []


def test_brana_shodi_build_pri_vystupu_s_parovanim(tmp_path):
    (tmp_path / "metodika").mkdir()
    for soubor in ("pilot-2026.09.json", "parovani-2026.09.json"):
        shutil.copy(KOREN / "metodika" / soubor, tmp_path / "metodika")
    (tmp_path / "vystupy").mkdir()
    (tmp_path / "vystupy" / "v.json").write_text(json.dumps([{"druh": "text", "text": "x", "shody": []}]), encoding="utf-8")
    assert publikace.main([str(tmp_path)]) == 1


def test_db_vysledek_bez_zakladu_nebo_srovnavaci_skupiny_nelze_ulozit(db, metodika_id):
    for sloupce, hodnoty in [("zaklad", "40"), ("srovnavaci_skupina", "'skupina'")]:
        db.execute("SAVEPOINT s")
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(f"INSERT INTO ind.indikator_vysledek (indikator_kod, obdobi_od, obdobi_do, pocet_pripadu, "
                       f"metodika_verze_id, {sloupce}) VALUES ('x', '2025-01-01', '2026-01-01', 40, %s, {hodnoty})",
                       (metodika_id,))
        db.execute("ROLLBACK TO SAVEPOINT s")
