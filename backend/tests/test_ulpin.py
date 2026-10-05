from __future__ import annotations

import pytest

from app.validators.ulpin import (
    ULPIN_LENGTH,
    geosix_ulpin_for,
    parse_ulpin,
    ulpin_errors,
    validate_ulpin,
)


def test_valid_ulpin_splits_into_hierarchical_segments() -> None:
    parts = validate_ulpin("12101055001700")

    assert parts.ulpin == "12101055001700"
    assert parts.state == "12"
    assert parts.district == "10"
    assert parts.sub_district == "105"
    assert parts.village == "500"
    assert parts.plot == "1700"
    assert parts.jurisdiction == "12/10/105/500"


def test_segment_widths_account_for_every_character() -> None:
    candidate = "99999999999999"
    parts = validate_ulpin(candidate)
    assert (
        len(parts.state)
        + len(parts.district)
        + len(parts.sub_district)
        + len(parts.village)
        + len(parts.plot)
        == ULPIN_LENGTH
    )


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("", "ulpin_empty"),
        ("   ", "ulpin_empty"),
        ("1210105500017", "ulpin_length"),
        ("121010550001700000", "ulpin_length"),
        ("1210105500017000A", "ulpin_charset"),
        ("12101055-017000", "ulpin_charset"),
        ("GEOSX00001", "ulpin_length"),
        ("GEOSX00001", "ulpin_charset"),
    ],
)
def test_malformed_ulpin_is_rejected_with_a_reason(value: str, code: str) -> None:
    codes = [error.code for error in ulpin_errors(value)]
    assert code in codes


def test_short_ulpin_reports_both_length_and_charset_when_applicable() -> None:
    codes = {error.code for error in ulpin_errors("12A")}
    assert "ulpin_length" in codes
    assert "ulpin_charset" in codes


def test_parse_returns_none_instead_of_raising_on_bad_input() -> None:
    assert parse_ulpin("nope") is None
    assert parse_ulpin("") is None


def test_geosix_key_is_derived_from_the_plot_serial() -> None:
    parts = validate_ulpin("12101055001700")
    assert geosix_ulpin_for(parts) == "GEOSX01700"


def test_geosix_key_preserves_leading_zeros_in_the_plot_serial() -> None:
    parts = validate_ulpin("12101055001111")
    assert geosix_ulpin_for(parts) == "GEOSX01111"


def test_geosix_key_matches_the_shape_the_vdc_parser_accepts() -> None:
    """The derived key must satisfy the existing VDC ULPIN grammar.

    Otherwise a parcel anchored to a national ULPIN could not take part in VDC
    generation, which would make the mapping useless.
    """
    import re

    from app.validators.vdc_parser import ULPIN_RE

    for national in (
        "12101055001700",
        "12101055001112",
        "09999999999999",
    ):
        assert re.match(ULPIN_RE, geosix_ulpin_for(validate_ulpin(national)))


def test_validation_reports_every_distinct_problem() -> None:
    with pytest.raises(ValueError) as raised:
        validate_ulpin("abc")
    message = str(raised.value)
    assert "14 characters" in message
    assert "digits only" in message
