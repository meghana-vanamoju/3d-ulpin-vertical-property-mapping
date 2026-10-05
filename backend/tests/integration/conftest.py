"""Fixtures for integration tests that run against a real PostgreSQL/PostGIS DB.

Isolation strategy
------------------
The application services call ``db.commit()`` internally, so a naive "yield a
session, roll it back at the end" fixture leaks committed rows between tests.
This module avoids that with the standard nested-transaction pattern:

1. Check out **one** connection from a dedicated test engine.
2. ``begin()`` an outer transaction on that connection.
3. Bind a ``Session`` to the *connection* with
   ``join_transaction_mode="conditional_savepoint"``, so the session's
   ``commit()`` only releases a SAVEPOINT and never the outer transaction.
4. Yield the session.
5. Always roll back the outer transaction, then close session and connection.

Because SAVEPOINTs nest inside the outer transaction, rolling that outer
transaction back discards everything any service committed. Verified in
``test_transaction_isolation.py``.

The application's own module-global engine is never used: ``app.main.lifespan``
probes it, and the dependency override below replaces ``get_db`` so requests
never touch it either. The ``TestClient`` is intentionally *not* used as a
context manager, because entering it would fire that lifespan.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.dependencies import get_current_user, get_db
from app.main import create_app
from app.models.floor import FloorType
from app.models.user import User, UserRole
from tests.auth_support import ADMIN_ID, SEED_EMAILS, bearer_headers, seed_password_hash
from tests.integration import factories

#: Environment variable holding the PostgreSQL/PostGIS test database DSN.
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"

_SKIP_REASON = (
    f"{TEST_DATABASE_URL_ENV} is not set. Integration tests require a migrated "
    "PostgreSQL/PostGIS database. Run `alembic upgrade head` against it, then "
    f"export {TEST_DATABASE_URL_ENV}=postgresql+psycopg://user:pass@host:5432/geosix_test"
)

#: ``parcels.ulpin`` is unique, and W19 requires a spec-valid ULPIN
#: (``GEOSX`` + exactly five digits) to generate a code. The counter keeps each
#: value unique within a test; leading zeros are legal for this segment.
_ulpin_counter = itertools.count(1)


def _valid_ulpin() -> str:
    """Return a unique, spec-valid ULPIN."""
    return f"GEOSX{next(_ulpin_counter):05d}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip the integration package when no test database is configured."""
    if os.environ.get(TEST_DATABASE_URL_ENV):
        return
    skip = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        if item.path.parent.name == "integration":
            item.add_marker(skip)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """The test database DSN, skipping the test when it is not configured."""
    url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not url:
        pytest.skip(_SKIP_REASON)
    assert url is not None  # narrowing for type checkers; pytest.skip never returns
    return url


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Generator[Engine, None, None]:
    """A dedicated engine for the test database.

    Created per session (not per test) so the connection pool and PostGIS
    prepared statements are reused across the run.
    """
    test_engine = create_engine(test_database_url, pool_pre_ping=True, future=True)
    try:
        yield test_engine
    finally:
        test_engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Session factory bound to the test engine.

    ``conditional_savepoint`` is the SQLAlchemy 2.x default and is stated
    explicitly here because the whole isolation guarantee depends on it: a
    service's ``db.commit()`` becomes a SAVEPOINT release, leaving the outer
    transaction open for the fixture to roll back.
    """
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        join_transaction_mode="conditional_savepoint",
    )


@pytest.fixture
def db_session(
    engine: Engine, session_factory: sessionmaker[Session]
) -> Generator[Session, None, None]:
    """A transaction-isolated session that undoes service-level commits.

    Calling ``rollback()`` on this session directly is *not* part of the
    supported contract: it can deassociate the outer transaction, after which a
    later write really commits and would permanently pollute the test database.
    Teardown detects that case and fails loudly rather than letting it pass
    silently.
    """
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = session_factory(bind=connection)
    try:
        yield session
    finally:
        session.close()
        if outer_transaction.is_active:
            outer_transaction.rollback()
        else:
            raise RuntimeError(
                "the test's outer transaction was deassociated before teardown, which means "
                "the test called rollback() on db_session (or committed the underlying "
                "connection). Rows may have been persisted to the test database. Use the "
                "db_session fixture's implicit rollback instead."
            )
        connection.close()


@pytest.fixture(scope="session")
def app_instance() -> Generator:
    """A fresh FastAPI app.

    Built with ``create_app()`` rather than reusing the module-global ``app`` so
    that no other test module's global mutation (for example a route registered
    for a different test) can leak in. No test-only routes or dependency
    overrides are installed on it here.
    """
    yield create_app()


@pytest.fixture
def client(app_instance, db_session: Session) -> Generator[TestClient, None, None]:
    """A TestClient whose requests run against the transaction-isolated session.

    Defaults to admin bearer credentials, because every data route now sits
    behind ``require_reader``/``require_editor``/``require_admin``. The admin
    user row is seeded inside the same transaction, so it disappears on
    rollback. Tests that need another identity can still pass explicit
    ``headers=`` per request (Starlette merges per-request headers over the
    client defaults).
    """
    admin = User(
        id=ADMIN_ID,
        email=SEED_EMAILS["admin"],
        password_hash=seed_password_hash(),
        full_name="Integration Admin",
        is_active=True,
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    db_session.flush()
    app_instance.dependency_overrides[get_db] = lambda: db_session
    # raise_server_exceptions=False so the application's own exception handlers
    # are exercised and produce the real error contract.
    test_client = TestClient(
        app_instance,
        raise_server_exceptions=False,
        headers=bearer_headers("admin"),
    )
    try:
        yield test_client
    finally:
        test_client.close()
        app_instance.dependency_overrides.pop(get_db, None)


@pytest.fixture
def ownership_client(client: TestClient) -> Generator[TestClient, None, None]:
    """Authenticate ownership API tests as an admin.

    A real ``User`` with the ``admin`` role is injected rather than bypassing
    the role dependency, so these tests exercise the same authorization path
    production uses. Passing ``admin`` also satisfies the stricter tier that
    ``delete_owner`` requires. Authorisation at the boundary -- reader being
    refused, editor being refused deletion -- is covered in
    ``tests/test_ownership_contracts.py``.
    """
    client.app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid4(),
        email="ownership-integration@example.com",
        password_hash="not-used",
        full_name="Ownership Integration",
        is_active=True,
        role=UserRole.ADMIN,
    )
    try:
        yield client
    finally:
        client.app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def reset_factories() -> Generator[None, None, None]:
    """Reset factory sequence counters around every test."""
    try:
        yield
    finally:
        factories.reset_factories()
        global _ulpin_counter
        _ulpin_counter = itertools.count(1)


@pytest.fixture
def parcel(db_session: Session):
    """A persisted parcel."""
    return factories.parcel_factory(db_session)


@pytest.fixture
def building(db_session: Session):
    """A persisted building, with its parent parcel."""
    return factories.building_factory(db_session)


@pytest.fixture
def floor(db_session: Session):
    """A persisted floor, with its parent building and parcel."""
    return factories.floor_factory(db_session)


@pytest.fixture
def unit(db_session: Session):
    """A persisted unit, with its full parent chain."""
    return factories.unit_factory(db_session)


# --------------------------------------------------------------------------
# W19: a hierarchy whose components are all valid VDC inputs
# --------------------------------------------------------------------------


@pytest.fixture
def vdc_parcel(db_session: Session):
    """A parcel carrying a spec-valid ULPIN."""
    return factories.parcel_factory(db_session, ulpin=_valid_ulpin())


@pytest.fixture
def vdc_building(db_session: Session, vdc_parcel):
    """A residential building on a parcel with a valid ULPIN (domain A)."""
    return factories.building_factory(db_session, parcel=vdc_parcel)


@pytest.fixture
def vdc_floor(db_session: Session, vdc_building):
    """A typical floor numbered 1, so the encoded level is ``F1``."""
    return factories.floor_factory(
        db_session, building=vdc_building, floor_number=1, floor_type=FloorType.TYPICAL
    )


@pytest.fixture
def vdc_unit(db_session: Session, vdc_floor):
    """A unit with a spec-valid identifier and no VDC code yet."""
    return factories.unit_factory(
        db_session, floor=vdc_floor, unit_identifier="U101", vdc_code=None
    )


@pytest.fixture
def healthy_database(engine: Engine) -> None:
    """Guard that the configured test database is really migrated PostGIS."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        postgis = connection.execute(text("SELECT PostGIS_Version()")).scalar()
    assert version is not None, "test database is not migrated (alembic_version is empty)"
    assert postgis, "test database does not have PostGIS installed"
