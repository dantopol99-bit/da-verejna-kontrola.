"""Sčítání napříč typy částek musí být technicky znemožněno (Python i databáze)."""

from decimal import Decimal

import psycopg
import pytest

from pvk.castka import (
    Castka,
    DphRezim,
    NesouhlasneCastky,
    NeuplnaCastka,
    Perioda,
    TypCastky,
    secti,
)


def c(hodnota, typ=TypCastky.SMLUVNI, mena="CZK", dph=DphRezim.BEZ_DPH, perioda=Perioda.CELKEM):
    return Castka(Decimal(hodnota), typ, mena, dph, perioda)


def test_soucet_stejneho_druhu():
    assert secti([c("10.50"), c("5"), c("0.50")]).hodnota == Decimal("16.00")
    assert (c("1") + c("2")).typ is TypCastky.SMLUVNI


@pytest.mark.parametrize(
    "jina",
    [
        c("1", typ=TypCastky.VYSOUTEZENA),
        c("1", mena="EUR"),
        c("1", dph=DphRezim.VCETNE_DPH),
        c("1", perioda=Perioda.ROCNI),
    ],
)
def test_soucet_ruznych_druhu_je_znemoznen(jina):
    with pytest.raises(NesouhlasneCastky):
        c("1") + jina
    with pytest.raises(NesouhlasneCastky):
        secti([c("1"), jina])


def test_vestavene_sum_nad_castkami_selze():
    with pytest.raises(NesouhlasneCastky):
        sum([c("1"), c("2")])


def test_scitani_s_cislem_selze():
    with pytest.raises(NesouhlasneCastky):
        c("1") + 1
    with pytest.raises(NesouhlasneCastky):
        c("1") + Decimal("1")


@pytest.mark.parametrize("pole", ["typ", "dph_rezim", "perioda"])
def test_castka_bez_typu_nevznikne(pole):
    argumenty = {"typ": TypCastky.SMLUVNI, "dph_rezim": DphRezim.BEZ_DPH, "perioda": Perioda.CELKEM}
    argumenty[pole] = None
    with pytest.raises(NeuplnaCastka):
        Castka(Decimal("1"), mena="CZK", **argumenty)


def test_castka_s_neplatnou_menou():
    with pytest.raises(NeuplnaCastka):
        c("1", mena="Kč")


def test_prazdny_soucet_nema_typ():
    with pytest.raises(ValueError):
        secti([])


# --- databáze ------------------------------------------------------------------------------------


def _tc(typ="smluvni", mena="CZK", dph="bez_dph", perioda="celkem", hodnota=10):
    return f"ROW('{typ}','{mena}','{dph}','{perioda}',{hodnota})::core.typovana_castka"


def test_db_soucet_stejneho_druhu(db):
    row = db.execute(f"SELECT (core.soucet(x)).hodnota AS h FROM (VALUES ({_tc()}), ({_tc(hodnota=5)})) v(x)").fetchone()
    assert row["h"] == 15


@pytest.mark.parametrize(
    "jina",
    [_tc(typ="vysoutezena"), _tc(mena="EUR"), _tc(dph="vcetne_dph"), _tc(perioda="rocni")],
)
def test_db_soucet_ruznych_druhu_selze(db, jina):
    with pytest.raises(psycopg.Error) as e:
        db.execute(f"SELECT core.soucet(x) FROM (VALUES ({_tc()}), ({jina})) v(x)")
    assert e.value.sqlstate == "PV003"


def test_db_neexistuje_sum_ani_plus_nad_typovanou_castkou(db):
    with pytest.raises(psycopg.errors.UndefinedFunction):
        db.execute(f"SELECT sum(x) FROM (VALUES ({_tc()})) v(x)")
    db.rollback()
    with pytest.raises(psycopg.errors.UndefinedFunction):
        db.execute(f"SELECT {_tc()} + {_tc()}")


def test_db_soucet_castky_bez_typu_selze(db):
    with pytest.raises(psycopg.Error) as e:
        db.execute("SELECT core.soucet(ROW(NULL,'CZK','bez_dph','celkem',1)::core.typovana_castka)")
    assert e.value.sqlstate == "PV003"
