from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.dependencies import get_current_user
from app.main import create_app
from app.models.user import User, UserRole
from app.schemas.ownership import OwnershipGrant, OwnerUpdate


def test_owner_patch_requires_a_non_null_mutable_field() -> None:
    with pytest.raises(ValidationError):
        OwnerUpdate()
    with pytest.raises(ValidationError):
        OwnerUpdate(name=None)
    with pytest.raises(ValidationError):
        OwnerUpdate(kind=None)


def test_grant_requires_timezone_aware_effective_date() -> None:
    with pytest.raises(ValidationError):
        OwnershipGrant(
            subject_type="parcel",
            subject_id="00000000-0000-0000-0000-000000000001",
            owner_id="00000000-0000-0000-0000-000000000002",
            share_basis_points=5000,
            valid_from=datetime(2026, 9, 30),
        )


OWNERSHIP_WRITE_ROUTES = [
    ("POST", "/api/v1/ownership/owners"),
    ("PATCH", "/api/v1/ownership/owners/{owner_id}"),
    ("DELETE", "/api/v1/ownership/owners/{owner_id}"),
    ("POST", "/api/v1/ownership/interests"),
    ("POST", "/api/v1/ownership/transfers"),
    ("POST", "/api/v1/ownership/interests/{interest_id}/revocations"),
]

#: Deleting an owner can destroy history a dispute depends on, so it is held to
#: the stricter tier. Everything else that mutates cadastral data is editor work.
ADMIN_ONLY_ROUTES = {("DELETE", "/api/v1/ownership/owners/{owner_id}")}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _match: str(uuid4()), path)


def _client_for(role: str | None) -> TestClient:
    """A client whose authenticated user holds ``role``.

    Overriding ``get_current_user`` keeps this test focused on tier
    enforcement. Resolving a real bearer token would also require seeded
    user rows, which belongs to the integration suite rather than to a
    schema-level contract check.
    """
    app = create_app()
    if role is not None:
        user = User(
            id=uuid4(),
            email=f"{role}@geosix.test",
            password_hash="not-used",
            full_name=role.title(),
            is_active=True,
            role=UserRole(role),
        )
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(("method", "path"), OWNERSHIP_WRITE_ROUTES)
def test_ownership_write_rejects_readers(method: str, path: str) -> None:
    """A valid session is not write permission: readers get 403, never 501."""
    client = _client_for("reader")
    try:
        response = client.request(method, _concrete(path), json={})
    finally:
        client.close()

    assert response.status_code == 403, response.text
    # 401/403 deliberately keep the legacy ``detail`` envelope; the
    # standardized ``error_code`` envelope covers every other status.
    assert response.json()["detail"]["error"]["code"] == "INSUFFICIENT_ROLE"


@pytest.mark.parametrize(("method", "path"), OWNERSHIP_WRITE_ROUTES)
def test_ownership_write_rejects_anonymous_callers(method: str, path: str) -> None:
    client = _client_for(None)
    try:
        response = client.request(method, _concrete(path), json={})
    finally:
        client.close()

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path"), OWNERSHIP_WRITE_ROUTES)
def test_ownership_write_is_not_left_unimplemented(method: str, path: str) -> None:
    """Regression guard: the Feature 2 gate used to return 501 for every write.

    An editor now reaches the handler, so the failure (if any) comes from
    request validation or the service -- never from an unimplemented gate.
    """
    client = _client_for("editor")
    try:
        response = client.request(method, _concrete(path), json={})
    finally:
        client.close()

    assert response.status_code != 501, "ownership writes are gated behind Feature 2 again"
    assert response.status_code != 500, response.text


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY_ROUTES)
def test_owner_deletion_requires_admin_not_merely_editor(method: str, path: str) -> None:
    client = _client_for("editor")
    try:
        response = client.request(method, _concrete(path), json={})
    finally:
        client.close()

    assert response.status_code == 403
    assert response.json()["detail"]["error"]["code"] == "INSUFFICIENT_ROLE"
