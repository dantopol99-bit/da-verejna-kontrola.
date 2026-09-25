import pytest

from pvk.ico import ico_platne, normalizuj_ico


@pytest.mark.parametrize("ico", ["00255513", "45023522", "70889546", "00006947", "03513386", "27502988"])
def test_platna_ica(ico):
    assert ico_platne(ico)


@pytest.mark.parametrize("ico", ["00255514", "1234567", "123456789", "abcdefgh", "", None, "0025551X"])
def test_neplatna_ica(ico):
    assert not ico_platne(ico)


@pytest.mark.parametrize(
    ("vstup", "vystup"),
    [
        ("00255513", "00255513"),
        ("255513", "00255513"),
        (255513, "00255513"),
        (255513.0, "00255513"),
        ("255513.0", "00255513"),
        ("CZ00255513", "00255513"),
        ("002 55 513", "00255513"),
        ("IČ 00255513", "00255513"),
        ("", None),
        (None, None),
        ("0", None),
        ("Mírové náměstí 1, 34101 Horažďovice", None),
        ("123456789", None),
    ],
)
def test_normalizace(vstup, vystup):
    assert normalizuj_ico(vstup) == vystup
