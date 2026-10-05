from __future__ import annotations

import uuid
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.audit import stamp_current_user
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole

security = HTTPBearer(auto_error=False)

DatabaseSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: DatabaseSession,
) -> User:
    """Validate a bearer access token and load the user from the database."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {"code": "AUTHENTICATION_REQUIRED", "message": "Authentication required"}
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_TOKEN", "message": "Invalid or expired token"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_TOKEN_TYPE", "message": "Invalid token type"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_TOKEN", "message": "Invalid or expired token"}},
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "USER_NOT_FOUND", "message": "User not found"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "INACTIVE_USER", "message": "User account is inactive"}},
        )
    # Attribute any audit-enabled rows written during this request to the user.
    stamp_current_user(db, user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

#: Ordered permission tiers; a role satisfies every requirement at or below its
#: own tier. Kept in sync with the permission matrix in ``docs/authentication.md``.
_ROLE_RANK: dict[UserRole, int] = {
    UserRole.READER: 1,
    UserRole.EDITOR: 2,
    UserRole.ADMIN: 3,
}


def require_role(minimum: UserRole) -> Callable[[User], User]:
    """Build a dependency that admits only users holding ``minimum`` or above.

    Returning the authenticated :class:`User` lets handlers reuse it (e.g. the
    admin endpoints) without a second lookup.
    """

    def dependency(user: CurrentUser) -> User:
        role = user.role if isinstance(user.role, UserRole) else UserRole(user.role)
        if _ROLE_RANK[role] < _ROLE_RANK[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "INSUFFICIENT_ROLE",
                        "message": (f"This action requires the '{minimum.value}' role or higher"),
                    }
                },
            )
        return user

    return dependency


#: Read access: any authenticated user (GET routes on data routers).
require_reader: Callable = require_role(UserRole.READER)
#: Write access: creating and updating cadastral data (POST/PUT/PATCH).
require_editor: Callable = require_role(UserRole.EDITOR)
#: Destructive and account-management actions (DELETE, user/role admin).
require_admin: Callable = require_role(UserRole.ADMIN)


#: Ownership mutations are gated on the same role tiers as the rest of the
#: cadastral API rather than a bespoke gate. Registering an owner, granting or
#: transferring an interest, and revoking one are ``editor`` actions: they
#: mutate cadastral data but are routine registry work. Deleting an owner is
#: ``admin`` because it can destroy history that a dispute may depend on.
require_ownership_editor: Callable = require_role(UserRole.EDITOR)
require_ownership_admin: Callable = require_role(UserRole.ADMIN)
