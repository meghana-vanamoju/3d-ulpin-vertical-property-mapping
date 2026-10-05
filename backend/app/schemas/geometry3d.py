from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.models.geometry3d import GeometryType


class Geometry3DCreate(BaseModel):
    """Request body for creating or replacing a unit's bounding-box geometry."""

    x_min: Decimal = Field(max_digits=18, decimal_places=6)
    x_max: Decimal = Field(max_digits=18, decimal_places=6)
    y_min: Decimal = Field(max_digits=18, decimal_places=6)
    y_max: Decimal = Field(max_digits=18, decimal_places=6)
    z_min: Decimal = Field(max_digits=18, decimal_places=6)
    z_max: Decimal = Field(max_digits=18, decimal_places=6)
    geometry_type: GeometryType

    @field_validator("x_max", "y_max", "z_max")
    @classmethod
    def validate_axis_bounds(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        axis = info.field_name[0]
        minimum = info.data.get(f"{axis}_min")
        if minimum is not None and minimum >= value:
            raise ValueError(f"{axis}_min must be less than {axis}_max")
        return value


class Geometry3DResponse(BaseModel):
    """Persisted bounding-box geometry and its derived measurements."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    unit_id: UUID
    x_min: Decimal
    x_max: Decimal
    y_min: Decimal
    y_max: Decimal
    z_min: Decimal
    z_max: Decimal
    geometry_type: GeometryType
    created_at: datetime
    updated_at: datetime
    volume: Decimal
    centroid: tuple[Decimal, Decimal, Decimal]
    dimensions: tuple[Decimal, Decimal, Decimal]


class GeometryValidationInput(BaseModel):
    """Bounding-box values accepted by the 3D geometry validator."""

    model_config = ConfigDict(from_attributes=True)

    x_min: Decimal | None = None
    x_max: Decimal | None = None
    y_min: Decimal | None = None
    y_max: Decimal | None = None
    z_min: Decimal | None = None
    z_max: Decimal | None = None


class ValidationIssue(BaseModel):
    """A single structured geometry validation error or warning."""

    code: Literal[
        "MISSING_GEOMETRY",
        "INVALID_DIMENSIONS",
        "ZERO_VOLUME",
        "DIMENSION_BELOW_THRESHOLD",
        "DIMENSION_EXCEEDS_LOCAL_FRAME",
    ]
    message: str
    field: str


class ValidationResult(BaseModel):
    """Structured outcome returned when validating a 3D geometry."""

    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
