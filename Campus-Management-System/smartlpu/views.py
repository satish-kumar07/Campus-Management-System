from django.contrib.auth.views import LoginView
from django.urls import reverse


class RoleAwareLoginView(LoginView):
    def form_valid(self, form):
        user = form.get_user()
        role = (self.request.POST.get("login_as") or "").strip().lower()
        if role:
            is_faculty = bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))
            is_vendor = bool(getattr(user, "groups", None) and user.groups.filter(name="VENDOR").exists())
            is_student = bool(getattr(user, "groups", None) and user.groups.filter(name="STUDENT").exists())

            allowed = False
            if role == "faculty":
                allowed = is_faculty
            elif role == "vendor":
                allowed = is_vendor
            elif role == "student":
                allowed = is_student

            if not allowed:
                form.add_error(None, "Selected role does not match this account.")
                return self.form_invalid(form)

            self.request.session["login_as"] = role

        return super().form_valid(form)

    def get_success_url(self):
        user = getattr(self.request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            role = (self.request.session.pop("login_as", "") or "").strip().lower()
            if role == "faculty":
                return reverse("faculty_dashboard")
            if role == "vendor":
                return reverse("food_vendor_dashboard")
            if role == "student":
                return reverse("student_dashboard")

            if user.is_superuser or user.is_staff:
                return reverse("faculty_dashboard")
            if user.groups.filter(name="VENDOR").exists():
                return reverse("food_vendor_dashboard")
            if user.groups.filter(name="STUDENT").exists():
                return reverse("student_dashboard")
        return super().get_success_url()
