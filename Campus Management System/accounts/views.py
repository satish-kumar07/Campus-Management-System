from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .forms import ProfileUpdateForm, StyledPasswordChangeForm


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
