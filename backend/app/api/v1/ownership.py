from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.dependencies import (
    CurrentUser,
    DatabaseSession,
    require_admin,
    require_editor,
    require_reader,
)
from app.schemas.error import ErrorResponse
from app.schemas.ownership import (
    OwnerCreate,
    OwnerListResponse,
    OwnerResponse,
    OwnershipGrant,
    OwnershipInterestListResponse,
    OwnershipInterestResponse,
    OwnershipRevocation,
    OwnershipTransfer,
    OwnershipTransferResponse,
    OwnerUpdate,
)
from app.services.ownership import (
    OwnershipError,
    create_owner,
    delete_owner,
    get_owner,
    grant_interest,
    list_interests,
    list_owners,
    revoke_interest,
    transfer_ownership,
    update_owner,
)

router = APIRouter(dependencies=[Depends(require_reader)])


def _raise_api_error(error: OwnershipError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details or {},
            }
        },
    ) from error


@router.post(
    "/owners",
    response_model=OwnerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an owner",
    description=(
        "Create an individual or organization owner record. Identifier is an opaque project value."
    ),
    responses={
        201: {"description": "Owner registered"},
        401: {"description": "Authentication required"},
        501: {
            "model": ErrorResponse,
            "description": "Feature 2 write authorization is unavailable",
        },
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
    dependencies=[Depends(require_editor)],
)
async def create_owner_route(
    body: OwnerCreate,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    try:
        return create_owner(db, body)
    except OwnershipError as error:
        _raise_api_error(error)


@router.get(
    "/owners",
    response_model=OwnerListResponse,
    summary="List owners",
    description="Search and paginate registered owners.",
    responses={401: {"description": "Authentication required"}},
)
async def list_owners_route(
    db: DatabaseSession,
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=255),
):
    return list_owners(db, page=page, per_page=per_page, search=search)


@router.get(
    "/owners/{owner_id}",
    response_model=OwnerResponse,
    summary="Get an owner",
    responses={
        401: {"description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Owner not found"},
    },
)
async def get_owner_route(owner_id: UUID, db: DatabaseSession, current_user: CurrentUser):
    try:
        return get_owner(db, owner_id)
    except OwnershipError as error:
        _raise_api_error(error)


@router.patch(
    "/owners/{owner_id}",
    response_model=OwnerResponse,
    summary="Update an owner",
    responses={
        401: {"description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Owner not found"},
        501: {
            "model": ErrorResponse,
            "description": "Feature 2 write authorization is unavailable",
        },
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
    dependencies=[Depends(require_editor)],
)
async def update_owner_route(
    owner_id: UUID,
    body: OwnerUpdate,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    try:
        return update_owner(db, owner_id, body)
    except OwnershipError as error:
        _raise_api_error(error)


@router.delete(
    "/owners/{owner_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unused owner",
    description="Owners referenced by any historical interest cannot be deleted.",
    responses={
        204: {"description": "Owner deleted"},
        401: {"description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Owner not found"},
        409: {"model": ErrorResponse, "description": "Owner has ownership history"},
        501: {
            "model": ErrorResponse,
            "description": "Feature 2 write authorization is unavailable",
        },
    },
    dependencies=[Depends(require_admin)],
)
async def delete_owner_route(
    owner_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    try:
        delete_owner(db, owner_id)
    except OwnershipError as error:
        _raise_api_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/interests",
    response_model=OwnershipInterestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant an ownership interest",
    description=(
        "Add a basis-point allocation from its effective start, subject to "
        "overlap and share limits."
    ),
    responses={
        201: {"description": "Interest granted"},
        401: {"description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Owner or subject not found"},
        409: {"model": ErrorResponse, "description": "Share or interval conflict"},
        501: {
            "model": ErrorResponse,
            "description": "Feature 2 write authorization is unavailable",
        },
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
    dependencies=[Depends(require_editor)],
)
async def grant_interest_route(
    body: OwnershipGrant,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    try:
        return grant_interest(db, body)
    except OwnershipError as error:
        _raise_api_error(error)


@router.post(
    "/transfers",
    response_model=OwnershipTransferResponse,
    summary="Transfer an ownership allocation",
    description=(
        "Atomically close the allocation effective at the transfer time and create a complete "
        "replacement allocation with the same total basis points."
    ),
    responses={
        200: {"description": "Allocation transferred"},
        401: {"description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Owner or subject not found"},
        409: {"model": ErrorResponse, "description": "Transfer conflict"},
        501: {
            "model": ErrorResponse,
            "description": "Feature 2 write authorization is unavailable",
        },
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
    dependencies=[Depends(require_editor)],
)
async def transfer_ownership_route(
    body: OwnershipTransfer,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    try:
        return transfer_ownership(db, body)
    except OwnershipError as error:
        _raise_api_error(error)


@router.post(
    "/interests/{interest_id}/revocations",
    response_model=OwnershipInterestResponse,
    summary="Revoke an ownership interest",
    description="Close an interest interval without deleting its historical record.",
    responses={
        200: {"description": "Interest revoked"},
        401: {"description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Interest not found"},
        409: {"model": ErrorResponse, "description": "Interest already closed"},
        501: {
            "model": ErrorResponse,
            "description": "Feature 2 write authorization is unavailable",
        },
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
    dependencies=[Depends(require_editor)],
)
async def revoke_interest_route(
    interest_id: UUID,
    body: OwnershipRevocation,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    try:
        return revoke_interest(db, interest_id, body)
    except OwnershipError as error:
        _raise_api_error(error)


def _list_params(
    db: DatabaseSession,
    current_user: dict,
    page: int,
    per_page: int,
    history: bool,
    effective_at: datetime | None,
    *,
    owner_id: UUID | None = None,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
) -> OwnershipInterestListResponse:
    try:
        return list_interests(
            db,
            owner_id=owner_id,
            subject_type=subject_type,
            subject_id=subject_id,
            page=page,
            per_page=per_page,
            history=history,
            effective_at=effective_at,
        )
    except OwnershipError as error:
        _raise_api_error(error)


def _list_query_params(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    history: bool = Query(default=False),
    effective_at: datetime | None = Query(default=None),
):
    if effective_at is not None and (
        effective_at.tzinfo is None or effective_at.utcoffset() is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "effective_at must include a timezone",
                    "details": {"effective_at": "A timezone offset is required"},
                }
            },
        )
    return page, per_page, history, effective_at


ListQuery = Annotated[tuple[int, int, bool, datetime | None], Depends(_list_query_params)]


@router.get(
    "/parcels/{parcel_id}/interests",
    response_model=OwnershipInterestListResponse,
    summary="List parcel ownership interests",
    responses={401: {"description": "Authentication required"}, 404: {"model": ErrorResponse}},
)
async def list_parcel_interests(
    parcel_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    query: ListQuery,
):
    page, per_page, history, effective_at = query
    return _list_params(
        db,
        current_user,
        page,
        per_page,
        history,
        effective_at,
        subject_type="parcel",
        subject_id=parcel_id,
    )


@router.get(
    "/units/{unit_id}/interests",
    response_model=OwnershipInterestListResponse,
    summary="List unit ownership interests",
    responses={401: {"description": "Authentication required"}, 404: {"model": ErrorResponse}},
)
async def list_unit_interests(
    unit_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    query: ListQuery,
):
    page, per_page, history, effective_at = query
    return _list_params(
        db,
        current_user,
        page,
        per_page,
        history,
        effective_at,
        subject_type="unit",
        subject_id=unit_id,
    )


@router.get(
    "/owners/{owner_id}/interests",
    response_model=OwnershipInterestListResponse,
    summary="List owner interests",
    responses={401: {"description": "Authentication required"}, 404: {"model": ErrorResponse}},
)
async def list_owner_interests(
    owner_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    query: ListQuery,
):
    page, per_page, history, effective_at = query
    return _list_params(
        db,
        current_user,
        page,
        per_page,
        history,
        effective_at,
        owner_id=owner_id,
    )
