from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Enum, Float, inspect, text
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    Building,
    BuildingType,
    ConstructionStatus,
    Floor,
    FloorType,
    GeometryType,
    Parcel,
    ParcelStatus,
    PropertyGeometry,
    Unit,
    UnitStatus,
    UnitType,
)
from tests.integration import factories

pytestmark = pytest.mark.integration


_POSTGRES_CAST = re.compile(r"::[A-Za-z_][A-Za-z0-9_]*(?:\s+[A-Za-z_][A-Za-z0-9_]*)*(?:\s*\[\])?")


def _normalized_sql(value: Any) -> str | None:
    if value is None:
        return None
    sql = re.sub(r"\s+", " ", str(value).replace('"', "").strip()).lower()
    # PostgreSQL reflects a normalized rewrite rather than the SQL that was
    # written: it parenthesises each operand and casts integer literals to the
    # column type, so `x_max - x_min <= 10000` comes back as
    # `((x_max - x_min) <= (10000)::numeric)`. Stripping the casts and
    # redundant grouping lets the two spellings of the same constraint compare
    # equal. Real drift -- a missing, renamed, or differently-bounded constraint
    # -- still compares unequal.
    sql = _POSTGRES_CAST.sub("", sql)
    sql = sql.replace("(", " ").replace(")", " ")
    return re.sub(r"\s+", " ", sql).strip()


def _constraint_name_matches(metadata_name: str | None, database_name: str | None) -> bool:
    return metadata_name is None or metadata_name == database_name


def _type_signature(column_type: Any, dialect: Any) -> tuple[Any, ...]:
    if isinstance(column_type, Float):
        return ("float", column_type.precision or 53)
    return (column_type.compile(dialect=dialect).casefold(),)


def _enum_types() -> dict[str, tuple[str, ...]]:
    return {
        column.type.name: tuple(column.type.enums)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Enum) and column.type.native_enum
    }


def test_live_schema_matches_base_metadata(engine) -> None:
    """Compare mapped application tables with the live migrated PostgreSQL schema."""
    database = inspect(engine)
    metadata_tables = set(Base.metadata.tables)
    live_tables = set(database.get_table_names(schema="public"))
    assert live_tables - {"alembic_version", "spatial_ref_sys"} == metadata_tables

    for table_name in sorted(metadata_tables):
        mapped_table = Base.metadata.tables[table_name]
        reflected_columns = {
            column["name"]: column for column in database.get_columns(table_name, schema="public")
        }
        assert set(reflected_columns) == set(mapped_table.columns.keys()), table_name

        for mapped_column in mapped_table.columns:
            reflected = reflected_columns[mapped_column.name]
            assert _type_signature(reflected["type"], engine.dialect) == _type_signature(
                mapped_column.type, engine.dialect
            ), f"{table_name}.{mapped_column.name} SQL type differs"
            assert reflected["nullable"] is mapped_column.nullable, (
                f"{table_name}.{mapped_column.name} nullability differs"
            )
            mapped_server_default = (
                mapped_column.server_default.arg
                if mapped_column.server_default is not None
                else None
            )
            assert _normalized_sql(reflected["default"]) == _normalized_sql(
                mapped_server_default
            ), f"{table_name}.{mapped_column.name} server default differs"

        primary_key = database.get_pk_constraint(table_name, schema="public")
        mapped_primary_key = next(
            constraint
            for constraint in mapped_table.constraints
            if constraint.__class__.__name__ == "PrimaryKeyConstraint"
        )
        assert tuple(primary_key["constrained_columns"] or ()) == tuple(
            column.name for column in mapped_primary_key.columns
        ), f"{table_name} primary key columns differ"
        assert _constraint_name_matches(mapped_primary_key.name, primary_key.get("name")), (
            f"{table_name} primary key name differs"
        )

        mapped_checks = {
            (constraint.name, _normalized_sql(constraint.sqltext))
            for constraint in mapped_table.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        }
        reflected_checks = {
            (constraint.get("name"), _normalized_sql(constraint["sqltext"]))
            for constraint in database.get_check_constraints(table_name, schema="public")
        }
        assert mapped_checks == reflected_checks, f"{table_name} CHECK constraints differ"

        mapped_uniques = {
            (constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in mapped_table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        reflected_uniques = {
            (constraint.get("name"), tuple(constraint.get("column_names") or ()))
            for constraint in database.get_unique_constraints(table_name, schema="public")
        }
        assert {columns for _, columns in mapped_uniques} == {
            columns for _, columns in reflected_uniques
        }, f"{table_name} UNIQUE columns differ"
        for mapped_name, mapped_columns in mapped_uniques:
            matching = next(
                columns for name, columns in reflected_uniques if columns == mapped_columns
            )
            reflected_name = next(
                name for name, columns in reflected_uniques if columns == matching
            )
            assert _constraint_name_matches(mapped_name, reflected_name), (
                f"{table_name} UNIQUE constraint name differs"
            )

        mapped_foreign_keys = {
            (
                constraint.name,
                tuple(element.parent.name for element in constraint.elements),
                constraint.elements[0].column.table.name,
                tuple(element.column.name for element in constraint.elements),
                constraint.ondelete,
            )
            for constraint in mapped_table.foreign_key_constraints
        }
        reflected_foreign_keys = {
            (
                constraint.get("name"),
                tuple(constraint.get("constrained_columns") or ()),
                constraint.get("referred_table"),
                tuple(constraint.get("referred_columns") or ()),
                (constraint.get("options") or {}).get("ondelete"),
            )
            for constraint in database.get_foreign_keys(table_name, schema="public")
        }
        assert {
            (local, target, remote, ondelete)
            for _, local, target, remote, ondelete in mapped_foreign_keys
        } == {
            (local, target, remote, ondelete)
            for _, local, target, remote, ondelete in reflected_foreign_keys
        }, f"{table_name} FOREIGN KEY definitions differ"
        for mapped_name, local, target, remote, ondelete in mapped_foreign_keys:
            matching = next(
                item
                for item in reflected_foreign_keys
                if (local, target, remote, ondelete) == item[1:]
            )
            assert _constraint_name_matches(mapped_name, matching[0]), (
                f"{table_name} FOREIGN KEY constraint name differs"
            )

        mapped_indexes = {
            (
                index.name,
                tuple(column.name for column in index.columns),
                bool(index.unique),
                index.dialect_options["postgresql"].get("using") or None,
            )
            for index in mapped_table.indexes
        }
        reflected_indexes = {
            (
                index.get("name"),
                tuple(index.get("column_names") or ()),
                bool(index.get("unique")),
                index.get("dialect_options", {}).get("postgresql_using"),
            )
            for index in database.get_indexes(table_name, schema="public")
            if not index.get("duplicates_constraint")
        }
        assert mapped_indexes == reflected_indexes, f"{table_name} indexes differ"

    live_enums = {
        item["name"]: tuple(item["labels"]) for item in inspect(engine).get_enums(schema="public")
    }
    for enum_name, labels in _enum_types().items():
        assert live_enums.get(enum_name) == labels, f"PostgreSQL enum {enum_name} labels differ"


def test_orm_timestamp_defaults_allow_inserts_without_timestamp_values(
    db_session: Session,
) -> None:
    """Every current table with created_at/updated_at accepts plain ORM inserts."""
    parcel = Parcel(
        parcel_identifier=f"TIMESTAMP-{uuid4().hex}",
        ulpin=f"TIMESTAMP-ULPIN-{uuid4().hex}",
        geometry=factories._geojson(factories.PARCEL_GEOMETRY),
        area_sqm=1000.0,
        status=ParcelStatus.ACTIVE,
        parcel_metadata={"source": "timestamp-contract"},
    )
    db_session.add(parcel)
    db_session.flush()

    building = Building(
        parcel_id=parcel.id,
        building_identifier=f"TIMESTAMP-BUILDING-{uuid4().hex}",
        building_type=BuildingType.RESIDENTIAL,
        construction_status=ConstructionStatus.COMPLETED,
        footprint_geometry=None,
    )
    db_session.add(building)
    db_session.flush()

    floor = Floor(
        building_id=building.id,
        floor_number=1,
        floor_type=FloorType.GROUND,
        elevation_min=Decimal("0"),
        elevation_max=Decimal("3"),
    )
    db_session.add(floor)
    db_session.flush()

    unit = Unit(
        floor_id=floor.id,
        unit_identifier=f"TIMESTAMP-UNIT-{uuid4().hex}",
        unit_type=UnitType.RESIDENTIAL,
        area_sqm=Decimal("75"),
        status=UnitStatus.ACTIVE,
    )
    unit.geometry = PropertyGeometry(
        x_min=Decimal("0"),
        x_max=Decimal("5"),
        y_min=Decimal("0"),
        y_max=Decimal("5"),
        z_min=Decimal("0"),
        z_max=Decimal("3"),
        geometry_type=GeometryType.AABB,
    )
    db_session.add(unit)
    db_session.flush()

    for instance in (parcel, building, floor, unit):
        assert instance.created_at.tzinfo is not None
        assert instance.updated_at.tzinfo is not None
        assert instance.created_at.utcoffset() == datetime.now(timezone.utc).utcoffset()
        assert instance.updated_at.utcoffset() == datetime.now(timezone.utc).utcoffset()

    created_updated_at = unit.updated_at
    unit.vdc_code = "TIMESTAMP-UPDATED"
    db_session.flush()
    assert unit.updated_at > created_updated_at


def _assert_enum_round_trip(
    db_session: Session,
    model: type,
    enum_member: PyEnum,
    attribute: str,
    table_name: str,
) -> None:
    instance = factories.__dict__[
        {
            Building: "building_factory",
            Floor: "floor_factory",
            Unit: "unit_factory",
            Parcel: "parcel_factory",
        }[model]
    ](db_session, **{attribute: enum_member})
    db_session.flush()
    instance_id = instance.id
    db_session.expire_all()

    loaded = db_session.get(model, instance_id)
    assert getattr(loaded, attribute) is enum_member
    raw_label = db_session.execute(
        text(f"SELECT {attribute}::text FROM {table_name} WHERE id = :id"),
        {"id": instance_id},
    ).scalar_one()
    assert raw_label == enum_member.value


@pytest.mark.parametrize("member", list(BuildingType))
def test_building_type_round_trips_as_native_enum(db_session: Session, member: BuildingType):
    _assert_enum_round_trip(db_session, Building, member, "building_type", "buildings")


@pytest.mark.parametrize("member", list(ConstructionStatus))
def test_construction_status_round_trips_as_native_enum(
    db_session: Session, member: ConstructionStatus
):
    _assert_enum_round_trip(db_session, Building, member, "construction_status", "buildings")


@pytest.mark.parametrize("member", list(FloorType))
def test_floor_type_round_trips_as_native_enum(db_session: Session, member: FloorType):
    _assert_enum_round_trip(db_session, Floor, member, "floor_type", "floors")


@pytest.mark.parametrize("member", list(UnitType))
def test_unit_type_round_trips_as_native_enum(db_session: Session, member: UnitType):
    _assert_enum_round_trip(db_session, Unit, member, "unit_type", "units")


@pytest.mark.parametrize("member", list(UnitStatus))
def test_unit_status_round_trips_as_native_enum(db_session: Session, member: UnitStatus):
    _assert_enum_round_trip(db_session, Unit, member, "status", "units")


@pytest.mark.parametrize("member", list(ParcelStatus))
def test_parcel_status_round_trips_as_native_enum(db_session: Session, member: ParcelStatus):
    _assert_enum_round_trip(db_session, Parcel, member, "status", "parcels")
