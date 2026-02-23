from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.auth.views import PasswordChangeView
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from faculty.models import Faculty

from .forms import FacultySignupForm, ProfileUpdateForm, StyledPasswordChangeForm


@login_required
def account_home(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/account_home.html", {})


@login_required
def edit_profile(request: HttpRequest) -> HttpResponse:
    user = request.user
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:home")
    else:
        form = ProfileUpdateForm(instance=user)

    return render(
        request,
        "accounts/edit_profile.html",
        {
            "form": form,
        },
    )


class AccountPasswordChangeView(PasswordChangeView):
    template_name = "accounts/change_password.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("accounts:home")

    def form_valid(self, form):
        res = super().form_valid(form)
        messages.success(self.request, "Password updated.")
        return res


change_password = login_required(AccountPasswordChangeView.as_view())


def faculty_signup(request: HttpRequest) -> HttpResponse:
    if getattr(request, "user", None) is not None and getattr(request.user, "is_authenticated", False):
        return redirect("home")

    if request.method == "POST":
        form = FacultySignupForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.email = (form.cleaned_data.get("email") or "").strip().lower()
                user.first_name = (form.cleaned_data.get("first_name") or "").strip()
                user.last_name = (form.cleaned_data.get("last_name") or "").strip()
                user.is_staff = True
                user.save()

                group, _ = Group.objects.get_or_create(name="FACULTY")
                user.groups.add(group)

                dept = (form.cleaned_data.get("department") or "").strip()
                full_name = f"{user.first_name} {user.last_name}".strip() or user.username
                Faculty.objects.update_or_create(
                    email=user.email,
                    defaults={"name": full_name, "department": dept},
                )

            messages.success(request, "Faculty account created. Please sign in as Faculty.")
            return redirect("login")
    else:
        form = FacultySignupForm()

    return render(request, "accounts/faculty_signup.html", {"form": form})
