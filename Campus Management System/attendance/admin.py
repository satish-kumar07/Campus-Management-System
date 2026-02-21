from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import AttendanceRecord, AttendanceSession, FaceSample, Notification, Student


class StudentAdminForm(forms.ModelForm):
    password1 = forms.CharField(required=False, widget=forms.PasswordInput)
    password2 = forms.CharField(required=False, widget=forms.PasswordInput)

    class Meta:
        model = Student
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        p1 = (cleaned.get("password1") or "").strip()
        p2 = (cleaned.get("password2") or "").strip()
        if p1 or p2:
            if p1 != p2:
                raise ValidationError("Passwords do not match")
            if len(p1) < 4:
                raise ValidationError("Password must be at least 4 characters")
        return cleaned


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    form = StudentAdminForm
    list_display = ("uid", "roll_no", "full_name", "email", "parent_phone")
    search_fields = ("uid", "roll_no", "full_name", "email")

    actions = ["generate_uid_and_create_user"]

    @admin.action(description="Generate UID + Create User for selected students")
    def generate_uid_and_create_user(self, request, queryset):
        User = get_user_model()
        group, _ = Group.objects.get_or_create(name="STUDENT")

        created = 0
        linked = 0
        skipped = 0

        with transaction.atomic():
            for s in queryset.select_for_update():
                # Ensure UID exists
                if s.uid is None:
                    s.save()

                username = str(s.uid)

                # If already linked, do nothing
                if s.user_id:
                    skipped += 1
                    continue

                # If username already exists, link it
                user = User.objects.filter(username=username).first()
                if user is None:
                    user = User(username=username)
                    if getattr(s, "email", ""):
                        user.email = s.email
                    # Initial password = roll_no (student can change after first login)
                    initial_password = (getattr(s, "roll_no", "") or "").strip()
                    if not initial_password:
                        skipped += 1
                        continue
                    user.set_password(initial_password)
                    user.save()
                    created += 1
                else:
                    linked += 1

                user.groups.add(group)
                s.user = user
                s.save(update_fields=["user"])

        messages.success(
            request,
            f"Generate UID + Create User: created={created}, linked_existing={linked}, skipped={skipped}. "
            "Initial password is the student's Roll No (they can change it after login).",
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        p1 = (form.cleaned_data.get("password1") or "").strip()
        if not p1:
            return

        User = get_user_model()
        username = str(obj.uid)

        user = obj.user
        if user is None:
            user = User.objects.filter(username=username).first()
        if user is None:
            user = User(username=username)

        if getattr(obj, "email", ""):
            user.email = obj.email
        user.set_password(p1)
        user.save()

        group, _ = Group.objects.get_or_create(name="STUDENT")
        user.groups.add(group)

        if obj.user_id != user.id:
            obj.user = user
            obj.save(update_fields=["user"])


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("course", "subject", "classroom", "session_start_at", "session_label", "created_at")
    list_filter = ("course", "subject", "classroom", "session_start_at")
    search_fields = ("course__code", "course__name", "session_label", "block")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("session", "student", "status", "source", "updated_at")
    list_filter = ("session__course", "session__session_date", "status", "source")
    search_fields = ("student__roll_no", "student__full_name")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient_student", "channel", "created_at")
    search_fields = ("recipient_student__roll_no", "recipient_student__full_name", "message")


@admin.register(FaceSample)
class FaceSampleAdmin(admin.ModelAdmin):
    list_display = ("student", "created_at")
    search_fields = ("student__roll_no", "student__full_name")

