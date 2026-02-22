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


def _in_group(user, group_name: str) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True
    return bool(user.groups.filter(name=group_name).exists())


def require_student(view_func: Callable):
    return user_passes_test(lambda u: _in_group(u, "STUDENT"))(view_func)
