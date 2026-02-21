def rbac_flags(request):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {"is_student": False}
    try:
        is_student = bool(user.groups.filter(name="STUDENT").exists())
    except Exception:
        is_student = False
    return {"is_student": is_student}
