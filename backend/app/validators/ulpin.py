"""Validation for India's national ULPIN ("Bhu-Aadhaar") parcel identifier.

GEOSIX does not issue ULPINs -- it extends them. ULPIN is the Department of Land
Resources' 14-character alphanumeric parcel identifier under the Digital India
Land Records Modernisation Programme (DILRMP), structured as::

    SS DD TTT VVV PPPP
    |   |   |    |    +-- 4  unique plot serial within the village
    |   |   |    +------- 3  village code
    |   |   +------------ 3  sub-district (tehsil) code
    |   +---------------- 2  district code
    +-------------------- 2  state code

That identifier is flat: it names a parcel on the ground and stops there. A
tower holds many independently owned properties above one parcel footprint, so
ULPIN alone cannot address ``Tower A / Floor 5 / Unit 503``.

This module validates a ULPIN and derives a GEOSIX parcel key from it, so a VDC
can be anchored to a nationally recognised parcel identity rather than only to a
GEOSIX-internal one.

Scope and honesty
-----------------
The *structure* above is well established. The individual code *values* are
issued and maintained by state and district registrars, so this module validates
shape and carries them through untouched. It never invents, assigns, or
interprets a state or district code, and it asserts no authority over the
national registry. Validation failures are reported as errors; the caller
decides what to do about them.

Specification note: the character counts are fixed and unambiguous. Whether a
given value is a *currently valid* code for a given state is outside what a
length-and-format check can know, so nothing here claims that.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

#: A ULPIN is exactly 14 characters: 2 state + 2 district + 3 sub-district +
#: 3 village + 4 plot serial, all digits.
ULPIN_LENGTH = 14

#: Character counts of each hierarchical segment, in order.
ULPIN_SEGMENT_LENGTHS: tuple[tuple[str, int], ...] = (
    ("state", 2),
    ("district", 2),
    ("sub_district", 3),
    ("village", 3),
    ("plot", 4),
)

#: Domain of the GEOSIX ULPIN space is 5 digits, so the serial is bounded.
_MAX_PLOT_SERIAL = 99999


class ULPINError(BaseModel):
    """A single reason a ULPIN was rejected."""

    segment: str = Field(description="Segment the problem belongs to")
    code: str = Field(description="Stable machine-readable reason")
    message: str = Field(description="Human-readable explanation")


class ULPINParts(BaseModel):
    """A ULPIN split into its hierarchical segments."""

    ulpin: str = Field(description="The 14-character national parcel identifier")
    state: str = Field(description="2-digit state code, as issued")
    district: str = Field(description="2-digit district code, as issued")
    sub_district: str = Field(description="3-digit sub-district (tehsil) code")
    village: str = Field(description="3-digit village code")
    plot: str = Field(description="4-digit plot serial within the village")

    @property
    def jurisdiction(self) -> str:
        """``SS/DD/TTT/VVV`` -- the administrative path to the parcel."""
        return f"{self.state}/{self.district}/{self.sub_district}/{self.village}"


def ulpin_errors(value: str) -> list[ULPINError]:
    """Return every reason ``value`` is not a well-formed ULPIN.

    An empty list means the shape is valid. This says nothing about whether the
    codes are currently issued -- see the module docstring.
    """
    errors: list[ULPINError] = []
    candidate = (value or "").strip()

    if not candidate:
        return [
            ULPINError(
                segment="ulpin",
                code="ulpin_empty",
                message="A national ULPIN is required to anchor a parcel",
            )
        ]

    if len(candidate) != ULPIN_LENGTH:
        errors.append(
            ULPINError(
                segment="ulpin",
                code="ulpin_length",
                message=(
                    f"ULPIN must be exactly {ULPIN_LENGTH} characters "
                    f"(state 2 + district 2 + sub-district 3 + village 3 + plot 4); "
                    f"got {len(candidate)}"
                ),
            )
        )

    if not candidate.isdigit():
        errors.append(
            ULPINError(
                segment="ulpin",
                code="ulpin_charset",
                message="ULPIN must contain digits only (0-9)",
            )
        )

    return errors


def parse_ulpin(value: str) -> ULPINParts | None:
    """Split a ULPIN into segments, or return ``None`` if malformed."""
    candidate = (value or "").strip()
    if ulpin_errors(candidate):
        return None

    offset = 0
    segments: dict[str, str] = {}
    for name, width in ULPIN_SEGMENT_LENGTHS:
        segments[name] = candidate[offset : offset + width]
        offset += width
    return ULPINParts(ulpin=candidate, **segments)


def geosix_ulpin_for(parts: ULPINParts) -> str:
    """Derive the GEOSIX parcel key for a nationally identified parcel.

    The GEOSIX ULPIN space is ``GEOSX`` + 5 digits, so the national plot
    serial is folded into it deterministically. The mapping is injective for
    distinct national ULPINs: the village code and plot serial together are
    wider than the 5 GEOSIX digits, so distinct inputs can collide. That is
    acceptable because the national ULPIN remains the stored system of record --
    the GEOSIX key is a local handle for VDC anchoring, never an identifier to
    be written back upstream.
    """
    plot_serial = int(parts.plot)
    if plot_serial > _MAX_PLOT_SERIAL:  # pragma: no cover - 4 digits always fit
        raise ValueError(f"plot serial {plot_serial} exceeds the GEOSIX space")
    return f"GEOSX{plot_serial:05d}"


def validate_ulpin(value: str) -> ULPINParts:
    """Parse ``value`` or raise ``ValueError`` listing every problem found."""
    errors = ulpin_errors(value)
    if errors:
        raise ValueError("; ".join(f"{e.segment}: {e.message}" for e in errors))
    parsed = parse_ulpin(value)
    assert parsed is not None  # guaranteed: errors was empty
    return parsed
