"""Root-only routes (spec §7 `-- root --`, §5 row 7 "Create/disable users, reset
passwords").

Three rules shape every handler here:

* **No public signup** (§5). Accounts are seeded or created by root, so creation
  is behind `require_root` and there is no unauthenticated path to it.
* **`is_root` is never settable.** §5's build decision is a single root account
  ("5 account rows, not 6"), and the request models have no such field — a second
  root is unrepresentable, not merely rejected. The one root also cannot
  deactivate itself, which would leave the system with nobody who can create
  users or restore it.
* **Users are never hard-deleted** (§5). Deactivation via `active = false` is the
  only removal, and it is immediate: it revokes the user's open sessions rather
  than waiting for their next login.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.config import settings
from app.deps import CurrentRoot, DbDep
from app.models import User
from app.schemas import PasswordResetIn, UserAdminOut, UserCreateIn, UserUpdateIn
from app.security import (
    ERROR_PASSWORD_TOO_SHORT,
    hash_password,
    password_too_short,
    unsign_token,
)
from app.sessions import revoke_all_sessions, revoke_other_sessions
from app.visibility import visible_users_stmt

router = APIRouter(prefix="/root", tags=["root"])

# §9 keeps user-visible strings in the dictionaries; details are machine codes.
ERROR_USER_NOT_FOUND = "user_not_found"
ERROR_USERNAME_TAKEN = "username_taken"
# §5: root is the only tier that can create or restore accounts. Deactivating the
# last active root would leave nobody able to undo it.
ERROR_LAST_ROOT = "last_root_required"


@router.get("/users", response_model=list[UserAdminOut])
def list_users(root: CurrentRoot, db: DbDep) -> list[User]:
    """§5: root sees every account, including its own row.

    Routed through `visible_users_stmt` even though the caller is always root and
    the filter is therefore always a no-op here. That is the point: the chokepoint
    is unconditional, so no future listing can be written without passing a viewer
    through it.
    """
    stmt = visible_users_stmt(root).order_by(User.id)
    return list(db.scalars(stmt).all())


@router.post("/users", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreateIn, root: CurrentRoot, db: DbDep) -> User:
    """§5 row 7: create an account. 409 `username_taken`, 422 if the password is
    below the shared §7 floor (`app.security`).

    The new account is active with `is_root=false` — the flag has no field in the
    request model at all (see the module docstring). `is_admin` is settable
    because §5 makes the admin a *visible* tier that root administers.
    """
    if password_too_short(body.password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERROR_PASSWORD_TOO_SHORT
        )
    if db.scalar(select(User.id).where(User.username == body.username)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_USERNAME_TAKEN)

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
        is_admin=body.is_admin,
        is_root=False,
        email=body.email,
        language=body.language,
        active=True,
    )
    db.add(user)
    db.flush()  # the audit row needs the new id
    audit.record(
        db,
        root,
        audit.ACTION_USER,
        "user",
        user.id,
        {
            "transition": "create",
            "username": user.username,
            "role": user.role.value,
            "is_admin": user.is_admin,
        },
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserAdminOut)
def update_user(user_id: int, body: UserUpdateIn, root: CurrentRoot, db: DbDep) -> User:
    """§5 row 7: edit an account, including deactivating it.

    A partial patch; `email` distinguishes absent from explicit null (clearing an
    address is a real operation), so it is read off `model_fields_set` rather than
    treated as "unchanged" when None.

    **Deactivation is immediate** (§5): setting `active=false` revokes every open
    session of that user in the same transaction, so a removed account stops being
    able to act now rather than at its next login. Deactivating the last active
    root is refused (409) — root is the only tier that can create or restore
    users, so it would be an unrecoverable state, and §5's "never hard-deleted"
    reasoning (history must stay attributable) applies with more force still to
    the account that administers everyone else.

    Reactivation (`active=true`) deliberately does NOT restore sessions: the rows
    are gone, and the user logs in again.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_USER_NOT_FOUND)

    changed: dict[str, object] = {}
    if body.display_name is not None:
        user.display_name = body.display_name
        changed["display_name"] = body.display_name
    if body.role is not None:
        user.role = body.role
        changed["role"] = body.role.value
    if body.language is not None:
        user.language = body.language
        changed["language"] = body.language.value
    if "email" in body.model_fields_set:
        user.email = body.email
        changed["email"] = body.email
    if body.is_admin is not None:
        user.is_admin = body.is_admin
        changed["is_admin"] = body.is_admin

    revoked = 0
    if body.active is not None and body.active is not user.active:
        if not body.active:
            _refuse_removing_the_last_root(db, user)
            revoked = revoke_all_sessions(db, user)
        user.active = body.active
        changed["active"] = body.active
        changed["sessions_revoked"] = revoked

    if changed:
        audit.record(
            db, root, audit.ACTION_USER, "user", user.id, {"transition": "update", **changed}
        )
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/password", response_model=UserAdminOut)
def reset_password(
    user_id: int,
    body: PasswordResetIn,
    root: CurrentRoot,
    db: DbDep,
    cookie: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    """§5 row 7: reset another account's password.

    No current password is required — that is what makes it a *reset* — so the
    authority is entirely the root tier's, and the act is audited with root as the
    actor. Every session of that user is revoked, on the same reasoning §5 gives
    for deactivation: a reset happens because the credential is compromised or the
    holder is gone, and leaving their cookie alive would defeat it.

    The one exception is root resetting its OWN password, where the caller's
    current session survives — logging someone out of the browser they just used
    to fix their credentials punishes them for doing it, and §7's `/me/settings`
    change makes the same allowance.
    """
    if password_too_short(body.new_password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERROR_PASSWORD_TOO_SHORT
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_USER_NOT_FOUND)

    user.password_hash = hash_password(body.new_password)
    if user.id == root.id:
        # Self-reset: keep the session this request arrived on, revoke the rest.
        # An absent or forged cookie unsigns to None, which only WIDENS the
        # revocation — it can never be used to preserve a session.
        revoked = revoke_other_sessions(db, user, unsign_token(cookie) if cookie else None)
    else:
        revoked = revoke_all_sessions(db, user)
    audit.record(
        db,
        root,
        audit.ACTION_CREDENTIAL,
        "user",
        user.id,
        {"change": "password_reset", "sessions_revoked": revoked},
    )
    db.commit()
    db.refresh(user)
    return user


def _refuse_removing_the_last_root(db: DbSession, user: User) -> None:
    """§5: never leave the system with no active root.

    Only root can create users, reset passwords or reactivate an account, so an
    installation with zero active roots cannot be repaired from inside the app.
    The check counts OTHER active roots rather than comparing ids, so it still
    holds if a future seed ever produced more than one.
    """
    if not user.is_root:
        return
    others = db.scalar(
        select(User.id).where(User.is_root.is_(True), User.active.is_(True), User.id != user.id)
    )
    if others is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_LAST_ROOT)
