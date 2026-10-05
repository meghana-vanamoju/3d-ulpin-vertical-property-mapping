"""Unit geometry must be rejected when it is expressed in the wrong frame.

Unit AABBs live in a local metric frame. Parcel and building footprints are
geographic degrees. The ordering checks alone cannot tell those apart -- a box in
degrees satisfies ``min < max`` just as well as one in metres -- so these tests
pin the frame contract that the three new CHECK constraints and the
``DIMENSION_EXCEEDS_LOCAL_FRAME`` issue enforce.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.geometry3d import GeometryType, PropertyGeometry
from app.validators.geometry3d_validator import MAX_UNIT_EXTENT_METRES, validate_geometry


def _box(x_min, x_max, y_min=0, y_max=1, z_min=0, z_max=3) -> PropertyGeometry:
    return PropertyGeometry(
        unit_id=uuid.uuid4(),
        geometry_type=GeometryType.AABB,
        x_min=Decimal(str(x_min)),
        x_max=Decimal(str(x_max)),
        y_min=Decimal(str(y_min)),
        y_max=Decimal(str(y_max)),
        z_min=Decimal(str(z_min)),
        z_max=Decimal(str(z_max)),
    )


def test_realistic_unit_dimensions_are_accepted() -> None:
    result = validate_geometry(_box(0, 8, 0, 5, 0, 3))
    assert result.valid, [issue.code for issue in result.errors]


def test_small_degree_span_is_not_caught_by_extent_and_is_still_invalid() -> None:
    """Documents a real limit: a 0.001-degree span is 11 cm, not 100 km.

    An extent bound cannot catch this. It satisfies the ordering checks and is
    far below the frame bound, yet it is degrees rather than metres. The
    validator cannot tell it apart from a thin-but-real unit, so this is a known
    residual risk, recorded rather than papered over.
    """
    result = validate_geometry(_box(77.5946, 77.5956))
    assert result.valid, [issue.code for issue in result.errors]


def test_wide_degree_span_is_rejected_as_wrong_frame() -> None:
    """A span only reachable in degrees exceeds any plausible unit extent."""
    result = validate_geometry(_box(0, 20000))
    assert not result.valid
    assert "DIMENSION_EXCEEDS_LOCAL_FRAME" in {issue.code for issue in result.errors}


def test_extent_derived_from_degrees_is_rejected() -> None:
    """One degree of longitude is ~111 km, comfortably past the bound."""
    one_degree_in_metres = 111_320
    result = validate_geometry(_box(0, 1, 0, 1, 0, one_degree_in_metres))
    assert not result.valid
    assert "DIMENSION_EXCEEDS_LOCAL_FRAME" in {issue.code for issue in result.errors}


def test_height_from_a_dem_in_metres_is_not_mistaken_for_degrees() -> None:
    """A plausible skyscraper height must still pass."""
    result = validate_geometry(_box(0, 40, 0, 30, 0, 828))
    assert result.valid, [issue.code for issue in result.errors]


def test_extent_exactly_at_the_bound_is_accepted() -> None:
    limit = MAX_UNIT_EXTENT_METRES
    result = validate_geometry(_box(0, limit))
    assert result.valid, [issue.code for issue in result.errors]


def test_extent_just_beyond_the_bound_is_rejected() -> None:
    limit = MAX_UNIT_EXTENT_METRES
    result = validate_geometry(_box(0, limit + 1))
    assert not result.valid
    assert "DIMENSION_EXCEEDS_LOCAL_FRAME" in {issue.code for issue in result.errors}


def test_wrong_frame_is_distinguishable_from_a_malformed_box() -> None:
    """A frame error must not be reported as an ordering error, or vice versa."""
    # Inverted: ordering problem only, no frame problem.
    inverted = validate_geometry(_box(5, 1))
    assert {issue.code for issue in inverted.errors} == {"INVALID_DIMENSIONS"}

    # Correctly ordered but far beyond any unit: frame problem only.
    wrong_frame = validate_geometry(_box(0, 20000))
    assert {issue.code for issue in wrong_frame.errors} == {"DIMENSION_EXCEEDS_LOCAL_FRAME"}


def test_missing_geometry_is_still_reported_first() -> None:
    result = validate_geometry(None)
    assert not result.valid
    assert result.errors[0].code == "MISSING_GEOMETRY"
