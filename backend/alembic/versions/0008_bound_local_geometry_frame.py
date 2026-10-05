"""Extend the property-geometry checks to bound the local metric frame.

Revision ID: 0008_bound_local_geometry_frame
Revises: 0007_merge_rbac_and_ownership

Unit bounding boxes are stored in a local metric frame, while parcel and
building footprints use SRID 4326 degrees. The three existing CHECK constraints
only enforce ``min < max``, which a box expressed in degrees satisfies just as
happily as one in metres -- so a geographic coordinate pasted into a unit AABB
would be accepted and describe a millimetre-sized object at the wrong place on
Earth.

This adds a generous upper bound per axis (10 km, far above any real structure)
so that class of mistake fails loudly instead of silently.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_bound_local_geometry_frame"
down_revision: str | Sequence[str] | None = "0007_merge_rbac_and_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Widest single-unit extent accepted on any axis, in metres.
MAX_UNIT_EXTENT_METRES = 10000

_EXTENT_CHECKS = (
    ("x", "ck_property_geometry_x_extent_within_local_frame"),
    ("y", "ck_property_geometry_y_extent_within_local_frame"),
    ("z", "ck_property_geometry_z_extent_within_local_frame"),
)


def upgrade() -> None:
    for axis, name in _EXTENT_CHECKS:
        op.create_check_constraint(
            name,
            "property_geometry",
            f"{axis}_max - {axis}_min <= {MAX_UNIT_EXTENT_METRES}",
        )


def downgrade() -> None:
    for _axis, name in _EXTENT_CHECKS:
        op.drop_constraint(name, "property_geometry", type_="check")