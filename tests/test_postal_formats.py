"""Unit tests for postal-code normalization (soustruh finding #1 fuller fix)."""

import pytest

from postal_formats import normalize_postal_code


@pytest.mark.parametrize(
    ("country", "raw", "expected"),
    [
        # CZ: both the bare and the national form resolve to the canonical "110 00".
        ("CZ", "11000", "110 00"),
        ("CZ", "110 00", "110 00"),
        ("CZ", "cz", "cz"),  # wrong length: left untouched, never invalidated
        # US has no separator format -> passthrough unchanged.
        ("US", "10001", "10001"),
        # GB / UK: single space so the last 3 chars are the inward code.
        ("GB", "sw1a1aa", "SW1A 1AA"),
        ("GB", "SW1A 1AA", "SW1A 1AA"),
        ("GB", "gir0aa", "GIR 0AA"),
        # A dash-separated country reinserts the dash.
        ("PL", "00950", "00-950"),
        ("PL", "00-950", "00-950"),
        ("JP", "1000001", "100-0001"),
        # Netherlands mixes digits + letters with a space.
        ("NL", "1011ac", "1011 AC"),
        # Unknown country -> passthrough.
        ("XX", "12345", "12345"),
        ("ZZ", "abc-def", "abc-def"),
        # Country code case / whitespace is normalized.
        ("cz", "11000", "110 00"),
        (" CZ ", "11000", "110 00"),
    ],
)
def test_normalize_postal_code(country, raw, expected):
    assert normalize_postal_code(country, raw) == expected


def test_empty_and_none_are_safe():
    assert normalize_postal_code("CZ", None) is None
    assert normalize_postal_code("CZ", "") == ""
    assert normalize_postal_code("CZ", "   ") == "   "
    # No country context -> passthrough, never raises.
    assert normalize_postal_code(None, "11000") == "11000"
    assert normalize_postal_code("", "11000") == "11000"


def test_never_invalidates_a_valid_canonical_input():
    # Feeding an already-canonical code back through is idempotent for every
    # separator-bearing country in the map.
    from postal_formats import POSTAL_FORMATS

    for cc, template in POSTAL_FORMATS.items():
        canonical = template.replace("#", "1").replace("@", "A")
        assert normalize_postal_code(cc, canonical) == canonical
