from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm

User = get_user_model()


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["first_name", "last_name", "email"]:
            if name in self.fields:
                self.fields[name].widget.attrs.update({"class": "form-control"})

        if "email" in self.fields:
            self.fields["email"].required = False

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        return email


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["old_password", "new_password1", "new_password2"]:
            if name in self.fields:
                self.fields[name].widget.attrs.update({"class": "form-control"})
