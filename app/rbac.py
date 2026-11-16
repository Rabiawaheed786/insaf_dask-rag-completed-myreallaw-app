"""Role-based access: do saaf roles - super_admin aur user.

Purane staff roles (admin, coordinator, lawyer) mojooda modules ke liye barqarar hain, lekin
system-wide darwaze (users, stats, audit logs) sirf super_admin ke liye hain. Owner account
`python -m app.cli make-admin <email>` se super_admin banta hai.
"""
from fastapi import Depends, Header

from .auth import current_user
from .messages import fail
from .models import User

USER = "user"
SUPER_ADMIN = "super_admin"
LEGACY_ADMIN = "admin"
STAFF_ROLES = (SUPER_ADMIN, LEGACY_ADMIN, "coordinator", "lawyer")
ADMIN_ROLES = (SUPER_ADMIN, LEGACY_ADMIN)  # purana admin bhi admin ke kaam kar sakta hai


def get_current_user(user: User = Depends(current_user)) -> User:
    return user


def is_super_admin(user: User) -> bool:
    return user.role == SUPER_ADMIN


def require_super_admin(user: User = Depends(get_current_user),
                        x_lang: str | None = Header(default=None)) -> User:
    if not is_super_admin(user):
        raise fail(403, "forbidden", x_lang or user.language)
    return user
