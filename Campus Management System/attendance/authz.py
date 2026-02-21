from __future__ import annotations

from collections.abc import Callable

from django.contrib.auth.decorators import user_passes_test


def _is_teacher(user) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True
    return False


def require_teacher(view_func: Callable):
    return user_passes_test(_is_teacher)(view_func)
