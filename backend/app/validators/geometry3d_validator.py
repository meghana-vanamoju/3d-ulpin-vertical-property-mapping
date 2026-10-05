from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.models.geometry3d import PropertyGeometry
from app.schemas.geometry3d import GeometryValidationInput, ValidationIssue, ValidationResult

DEFAULT_MINIMUM_DIMENSION = Decimal("0.001")

#: Widest single-unit extent accepted on any axis, in metres. Unit geometry is
#: stored in a local metric frame; footprints use geographic degrees, so a
#: coordinate pasted from an SRID 4326 source lands far outside this bound.
MAX_UNIT_EXTENT_METRES = Decimal("10000")

_AXES = ("x", "y", "z")
_COORDINATES = tuple(f"{axis}_{side}" for axis in _AXES for side in ("min", "max"))


def validate_geometry(
    geometry: PropertyGeometry | GeometryValidationInput | None,
    *,
    minimum_dimension: Decimal | int | float = DEFAULT_MINIMUM_DIMENSION,
) -> ValidationResult:
    """Validate a 3D axis-aligned bounding box and return structured issues.

    The default minimum dimension is one millimeter, assuming coordinates are in meters.
    """
    threshold = _coerce_threshold(minimum_dimension)
    if geometry is None:
        return ValidationResult(
            valid=False,
            errors=[
                ValidationIssue(
                    code="MISSING_GEOMETRY",
                    message="Geometry is required.",
                    field="geometry",
                )
            ],
        )

    if isinstance(geometry, GeometryValidationInput):
        values = geometry
    else:
        if not isinstance(geometry, PropertyGeometry):
            raise TypeError("geometry must be a PropertyGeometry or GeometryValidationInput")
        try:
            values = GeometryValidationInput.model_validate(geometry, from_attributes=True)
        except ValidationError as error:
            invalid_coordinates = {
                str(issue["loc"][0])
                for issue in error.errors()
                if issue.get("loc") and issue["loc"][0] in _COORDINATES
            }
            return ValidationResult(
                valid=False,
                errors=[
                    ValidationIssue(
                        code="INVALID_DIMENSIONS",
                        message=f"Bounding box coordinate {coordinate} must be a finite number.",
                        field=coordinate,
                    )
                    for coordinate in _COORDINATES
                    if coordinate in invalid_coordinates
                ],
            )

    missing = [coordinate for coordinate in _COORDINATES if getattr(values, coordinate) is None]
    if missing:
        return ValidationResult(
            valid=False,
            errors=[
                ValidationIssue(
                    code="MISSING_GEOMETRY",
                    message=f"Bounding box coordinate {coordinate} is required.",
                    field=coordinate,
                )
                for coordinate in missing
            ],
        )

    errors: list[ValidationIssue] = []
    dimensions: dict[str, Decimal] = {}
    for axis in _AXES:
        minimum = getattr(values, f"{axis}_min")
        maximum = getattr(values, f"{axis}_max")
        if not minimum.is_finite() or not maximum.is_finite():
            errors.append(
                ValidationIssue(
                    code="INVALID_DIMENSIONS",
                    message=f"{axis.upper()} coordinates must be finite numbers.",
                    field=axis,
                )
            )
            continue

        dimension = maximum - minimum
        dimensions[axis] = dimension
        if dimension < 0:
            errors.append(
                ValidationIssue(
                    code="INVALID_DIMENSIONS",
                    message=f"{axis}_min must be less than {axis}_max.",
                    field=axis,
                )
            )
        elif dimension == 0:
            errors.append(
                ValidationIssue(
                    code="ZERO_VOLUME",
                    message=f"{axis}_min and {axis}_max produce a zero-size dimension.",
                    field=axis,
                )
            )
        elif dimension < threshold:
            errors.append(
                ValidationIssue(
                    code="DIMENSION_BELOW_THRESHOLD",
                    message=(
                        f"{axis.upper()} dimension {dimension} is below the minimum "
                        f"dimension {threshold}."
                    ),
                    field=axis,
                )
            )

    if not errors and dimensions["x"] * dimensions["y"] * dimensions["z"] <= 0:
        errors.append(
            ValidationIssue(
                code="ZERO_VOLUME",
                message="Bounding box volume must be positive.",
                field="volume",
            )
        )

    errors.extend(_frame_errors(dimensions))

    return ValidationResult(valid=not errors, errors=errors)


def _frame_errors(dimensions: dict[str, Decimal]) -> list[ValidationIssue]:
    """Reject geometry that cannot have come from the local metric frame.

    Unit AABBs are metres; parcel and building footprints are geographic
    degrees. A latitude or longitude is at most 180 in magnitude, and even a
    whole degree is roughly 111 km, so any axis extent beyond
    ``MAX_UNIT_EXTENT_METRES`` means the caller supplied the wrong frame
    rather than a real structure. Reported separately from the ordering
    checks because it is a different class of mistake: not a malformed box
    but a box in the wrong units.
    """
    issues: list[ValidationIssue] = []
    for axis in _AXES:
        dimension = dimensions[axis]
        if dimension > MAX_UNIT_EXTENT_METRES:
            issues.append(
                ValidationIssue(
                    code="DIMENSION_EXCEEDS_LOCAL_FRAME",
                    message=(
                        f"{axis.upper()} extent {dimension} exceeds the maximum "
                        f"{MAX_UNIT_EXTENT_METRES} m for a single unit. Unit geometry is "
                        "stored in a local metric frame (metres); geographic coordinates "
                        "(degrees, e.g. from an SRID 4326 footprint) cannot be used here."
                    ),
                    field=axis,
                )
            )
    return issues


def _coerce_threshold(value: Decimal | int | float) -> Decimal:
    try:
        threshold = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("minimum_dimension must be a finite, non-negative number") from error
    if not threshold.is_finite() or threshold < 0:
        raise ValueError("minimum_dimension must be a finite, non-negative number")
    return threshold
