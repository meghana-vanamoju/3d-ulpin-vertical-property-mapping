from __future__ import annotations

import uuid
from decimal import Decimal
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Numeric, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.audit import AuditColumns
from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.unit import Unit


class GeometryType(PyEnum):
    """Geometry type enumeration - extensible for future geometry types."""

    AABB = "aabb"
    POLYGON_3D = "polygon_3d"


class PropertyGeometry(BaseModel, AuditColumns):
    """3D property geometry model using axis-aligned bounding boxes (AABB).

    Coordinate frame
    ----------------
    Unit AABBs are expressed in a **local metric frame (metres)**, not in
    geographic degrees. Parcel and building footprints use SRID 4326 degrees;
    mixing the two is a real hazard, because a box expressed in degrees
    satisfies ``x_min < x_max`` just as happily as one in metres and would
    pass every ordering check while describing a millimetre-sized object at
    the wrong place on Earth.

    The upper bounds below make that mistake fail loudly instead. They are
    far above any plausible building -- the tallest structure in the world
    is under 1km, and a single residential unit is a small fraction of that
    -- so they cannot reject legitimate data, while any value carrying a
    geographic coordinate (|value| > 180) is far outside them and is
    rejected by the database.
    """

    __tablename__ = "property_geometry"

    __table_args__ = (
        CheckConstraint(
            "x_min < x_max",
            name="ck_property_geometry_x_min_lt_x_max",
        ),
        CheckConstraint(
            "y_min < y_max",
            name="ck_property_geometry_y_min_lt_y_max",
        ),
        CheckConstraint(
            "z_min < z_max",
            name="ck_property_geometry_z_min_lt_z_max",
        ),
        CheckConstraint(
            "x_max - x_min <= 10000",
            name="ck_property_geometry_x_extent_within_local_frame",
        ),
        CheckConstraint(
            "y_max - y_min <= 10000",
            name="ck_property_geometry_y_extent_within_local_frame",
        ),
        CheckConstraint(
            "z_max - z_min <= 10000",
            name="ck_property_geometry_z_extent_within_local_frame",
        ),
        UniqueConstraint("unit_id", name="uq_property_geometry_unit_id"),
    )

    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    x_min: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=6), nullable=False)
    x_max: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=6), nullable=False)
    y_min: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=6), nullable=False)
    y_max: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=6), nullable=False)
    z_min: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=6), nullable=False)
    z_max: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=6), nullable=False)
    geometry_type: Mapped[GeometryType] = mapped_column(
        Enum(
            GeometryType,
            name="geometry_type",
            native_enum=True,
            values_callable=lambda enum_class: [item.value for item in enum_class],
        ),
        nullable=False,
        default=GeometryType.AABB,
    )

    unit: Mapped[Unit] = relationship(back_populates="geometry")

    @property
    def volume(self) -> Decimal:
        """Calculate the volume of the bounding box."""
        return (self.x_max - self.x_min) * (self.y_max - self.y_min) * (self.z_max - self.z_min)

    @property
    def centroid(self) -> tuple[Decimal, Decimal, Decimal]:
        """Calculate the centroid of the bounding box."""
        return (
            (self.x_min + self.x_max) / Decimal("2"),
            (self.y_min + self.y_max) / Decimal("2"),
            (self.z_min + self.z_max) / Decimal("2"),
        )

    @property
    def dimensions(self) -> tuple[Decimal, Decimal, Decimal]:
        """Calculate the dimensions of the bounding box."""
        return (
            self.x_max - self.x_min,
            self.y_max - self.y_min,
            self.z_max - self.z_min,
        )
