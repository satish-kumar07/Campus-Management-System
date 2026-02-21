from django.contrib.auth.views import LoginView
from django.urls import reverse


class RoleAwareLoginView(LoginView):
    def get_success_url(self):
        user = getattr(self.request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            if user.is_superuser or user.is_staff:
                return super().get_success_url()
            if user.groups.filter(name="VENDOR").exists():
                return reverse("food_vendor_dashboard")
            if user.groups.filter(name="STUDENT").exists():
                return reverse("food_home")
        return super().get_success_url()
