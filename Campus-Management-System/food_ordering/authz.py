from __future__ import annotations

from collections.abc import Callable

from django.contrib.auth.decorators import user_passes_test
from django.db.models import Q


def _in_group(user, group_name: str) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True
    return bool(user.groups.filter(name=group_name).exists())


def require_student(view_func: Callable):
    return user_passes_test(lambda u: _in_group(u, "STUDENT"))(view_func)


def require_vendor(view_func: Callable):
    def _is_vendor(u) -> bool:
        if _in_group(u, "VENDOR"):
            return True
        try:
            return bool(
                getattr(u, "is_authenticated", False)
                and (
                    u.operated_food_categories.exists()
                    or u.operated_food_stalls.exists()
                )
            )
        except Exception:
            return False

    return user_passes_test(_is_vendor)(view_func)
