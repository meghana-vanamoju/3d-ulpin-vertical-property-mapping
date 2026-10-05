# Canonical Unit Bounding Boxes

`property_geometry` is the single authoritative store for every unit's 3D
axis-aligned bounding box. The `units` table no longer stores a second copy.
Geometry validation, overlap and gap detection, elevation validation, and the
unit geometry API all read the canonical geometry record.

## API compatibility and validation

The unit create and update payloads retain their existing `x_min`, `x_max`,
`y_min`, `y_max`, `z_min`, and `z_max` fields. Unit responses continue returning
those fields, derived from `property_geometry`. Creating a unit creates its
canonical geometry in the same transaction; updating any bounds through the
unit API updates that same geometry record. The geometry endpoint can also
replace the record and its derived measurements.

All six coordinates must fit the canonical numeric precision (18 digits, with
up to 6 decimal places). Each axis must satisfy **strictly**
`min < max`. Equality was previously accepted by unit create/update validation;
zero-size dimensions are now rejected consistently by the unit API, geometry
API, and database constraints. This is a deliberate validation tightening;
the request and response field shapes remain compatible.

## Migration and existing records

Alembic revision `0005_unify_unit_property_geometry` backfills missing
`property_geometry` records from the previous `units` columns, preserves the
unit's timestamps, verifies row counts and coordinate equality, and then drops
the duplicate columns. Its downgrade restores the columns from the canonical
geometry values.

The upgrade does not silently discard conflicting data. Before changing the
schema it aborts with the affected unit IDs if existing copies disagree,
coordinates have zero/inverted dimensions, or values cannot fit the canonical
numeric precision without rounding. Reconcile those rows before retrying the
migration; the original unit columns remain in place when these preflight
checks fail.


## Coordinate frame

Unit bounding boxes are stored in a **local metric frame (metres)**, origin
arbitrary per building. Parcel and building footprints are stored separately in
**SRID 4326 (geographic degrees)**. The two are never mixed in one row, and the
API does not convert between them.

This distinction is enforced rather than merely documented. `x_min < x_max` and
its y/z counterparts are necessary but not sufficient: a box expressed in
degrees satisfies those ordering checks exactly as well as one in metres, and
would be accepted while describing a millimetre-sized object at the wrong place
on Earth. Three further constraints therefore bound each axis extent to 10 km
(`ck_property_geometry_*_extent_within_local_frame`) — far above any real
structure, but well below the ~111 km a single degree spans. The validator
reports the same condition as `DIMENSION_EXCEEDS_LOCAL_FRAME`.

**Known residual risk:** a small degree span (for example 0.001°, about 11 cm)
still passes, because it satisfies both the ordering checks and the extent
bound and is indistinguishable from a genuinely thin unit. Detecting that would
require comparing against a registered anchor transform, which GEOSIX does not
maintain. Coordinate provenance therefore remains the caller's responsibility.

Georeferencing unit volumes against footprints requires an anchor transform
between the local frame and SRID 4326. That is not implemented, which is why the
3D viewer renders unit volumes but not building or parcel outlines.
