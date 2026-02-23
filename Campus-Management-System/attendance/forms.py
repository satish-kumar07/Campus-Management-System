from datetime import datetime

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from courses.models import Course, Enrollment
from faculty.models import Faculty

from classrooms.models import Classroom
from blocks.models import Block

from .models import AttendanceSession, FaceSample, Student

from food_ordering.models import FoodStall, MenuCategory, MenuItem


User = get_user_model()


class VendorCreateForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Vendor username"}),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "Vendor email (optional)"}),
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Password"}),
        label="Password",
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Confirm password"}),
        label="Confirm Password",
    )
    stalls = forms.ModelMultipleChoiceField(
        queryset=FoodStall.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select"}),
        help_text="Assign this vendor as operator for selected stalls.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stalls"].queryset = FoodStall.objects.order_by("name")

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise forms.ValidationError("Username is required.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with this username already exists.")
        return username

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1") or ""
        p2 = cleaned.get("password2") or ""
        if p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        if not p1:
            raise forms.ValidationError("Password is required.")
        return cleaned


class FoodStallManageForm(forms.ModelForm):
    class Meta:
        model = FoodStall
        fields = ["name", "location", "is_active", "max_items_per_day", "operators"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "name" in self.fields:
            self.fields["name"].widget.attrs.update({"class": "form-control", "placeholder": "Stall name"})
        if "location" in self.fields:
            self.fields["location"].widget.attrs.update(
                {"class": "form-control", "placeholder": "Location (optional)"}
            )
        if "is_active" in self.fields:
            self.fields["is_active"].widget.attrs.update({"class": "form-check-input"})
        if "max_items_per_day" in self.fields:
            self.fields["max_items_per_day"].widget.attrs.update({"class": "form-control"})
        if "operators" in self.fields:
            self.fields["operators"].queryset = User.objects.order_by("username")
            self.fields["operators"].widget.attrs.update({"class": "form-select"})


class MenuCategoryManageForm(forms.ModelForm):
    class Meta:
        model = MenuCategory
        fields = ["stall", "name", "sort_order", "operators"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "stall" in self.fields:
            self.fields["stall"].queryset = FoodStall.objects.order_by("name")
            self.fields["stall"].widget.attrs.update({"class": "form-select"})
            self.fields["stall"].empty_label = "Select a stall"
        if "name" in self.fields:
            self.fields["name"].widget.attrs.update({"class": "form-control", "placeholder": "Category name"})
        if "sort_order" in self.fields:
            self.fields["sort_order"].widget.attrs.update({"class": "form-control"})
        if "operators" in self.fields:
            self.fields["operators"].queryset = User.objects.order_by("username")
            self.fields["operators"].widget.attrs.update({"class": "form-select"})


class MenuItemManageForm(forms.ModelForm):
    class Meta:
        model = MenuItem
        fields = ["stall", "category", "name", "price", "is_available", "prep_time_minutes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "stall" in self.fields:
            self.fields["stall"].queryset = FoodStall.objects.order_by("name")
            self.fields["stall"].widget.attrs.update({"class": "form-select"})
            self.fields["stall"].empty_label = "Select a stall"
        if "category" in self.fields:
            self.fields["category"].queryset = MenuCategory.objects.select_related("stall").order_by(
                "stall__name", "sort_order", "name"
            )
            self.fields["category"].widget.attrs.update({"class": "form-select"})
            self.fields["category"].required = False
        if "name" in self.fields:
            self.fields["name"].widget.attrs.update({"class": "form-control", "placeholder": "Item name"})
        if "price" in self.fields:
            self.fields["price"].widget.attrs.update({"class": "form-control"})
        if "is_available" in self.fields:
            self.fields["is_available"].widget.attrs.update({"class": "form-check-input"})
        if "prep_time_minutes" in self.fields:
            self.fields["prep_time_minutes"].widget.attrs.update({"class": "form-control"})


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        if not isinstance(data, (list, tuple)):
            data = [data]
        cleaned = []
        for d in data:
            cleaned.append(forms.FileField.clean(self, d, initial))
        return cleaned


class AttendanceSessionCreateForm(forms.ModelForm):
    session_start_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local", "class": "form-control", "step": "60"},
        ),
    )

    class Meta:
        model = AttendanceSession
        fields = ["course", "classroom", "block", "capacity", "session_start_at", "session_label"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("session_start_at") and not getattr(self.instance, "pk", None):
            now = timezone.localtime(timezone.now())
            now = (now.replace(second=0, microsecond=0) + timezone.timedelta(minutes=1))
            self.initial["session_start_at"] = now

        if "classroom" in self.fields:
            self.fields["classroom"].queryset = Classroom.objects.select_related("block").order_by(
                "block__name",
                "room_number",
            )
        
        # Configure all form fields
        field_configs = {
            "session_label": {
                "widget_attrs": {"class": "form-control", "placeholder": "Enter session label"}
            },
            "course": {
                "empty_label": "Select a course",
                "widget_attrs": {"class": "form-select"}
            },
            "classroom": {
                "empty_label": "Select a classroom",
                "widget_attrs": {"class": "form-select"}
            },
            "block": {
                "widget_attrs": {"class": "form-control", "placeholder": "e.g. A, B, C", "readonly": True}
            },
            "capacity": {
                "widget_attrs": {"class": "form-control", "placeholder": "e.g. 60", "readonly": True}
            }
        }
        
        for field_name, config in field_configs.items():
            if field_name in self.fields:
                if "widget_attrs" in config:
                    self.fields[field_name].widget.attrs.update(config["widget_attrs"])
                if "empty_label" in config:
                    self.fields[field_name].empty_label = config["empty_label"]

    def clean_session_start_at(self):
        dt = self.cleaned_data.get("session_start_at")
        if dt is None:
            return dt
        now = timezone.now()
        if dt < now:
            raise forms.ValidationError("Session time cannot be in the past.")
        return dt

    def save(self, commit=True):
        obj: AttendanceSession = super().save(commit=False)
        dt = self.cleaned_data.get("session_start_at")
        if dt is not None:
            local_dt = timezone.localtime(dt)
            obj.session_date = local_dt.date()
            obj.time_slot = local_dt.strftime("%H:%M")
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class CourseCreateForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["code", "name", "credits", "weekly_hours", "faculty", "classroom"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "code" in self.fields:
            self.fields["code"].widget.attrs.update(
                {"class": "form-control", "placeholder": "e.g. CSE111"}
            )
        if "name" in self.fields:
            self.fields["name"].widget.attrs.update(
                {"class": "form-control", "placeholder": "Enter course name"}
            )
        if "credits" in self.fields:
            self.fields["credits"].widget.attrs.update({"class": "form-control"})
        if "weekly_hours" in self.fields:
            self.fields["weekly_hours"].widget.attrs.update({"class": "form-control"})
        if "faculty" in self.fields:
            self.fields["faculty"].widget.attrs.update({"class": "form-select"})
        if "classroom" in self.fields:
            self.fields["classroom"].widget.attrs.update({"class": "form-select"})


class FacultyForm(forms.ModelForm):
    class Meta:
        model = Faculty
        fields = ["name", "department", "max_workload_hours", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "name" in self.fields:
            self.fields["name"].widget.attrs.update({"class": "form-control"})
        if "department" in self.fields:
            self.fields["department"].widget.attrs.update({"class": "form-control"})
        if "max_workload_hours" in self.fields:
            self.fields["max_workload_hours"].widget.attrs.update({"class": "form-control"})
        if "email" in self.fields:
            self.fields["email"].widget.attrs.update({"class": "form-control"})


class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ["block", "room_number", "capacity", "room_type"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "block" in self.fields:
            self.fields["block"].widget.attrs.update({"class": "form-select"})
        if "room_number" in self.fields:
            self.fields["room_number"].widget.attrs.update({"class": "form-control"})
        if "capacity" in self.fields:
            self.fields["capacity"].widget.attrs.update({"class": "form-control"})
        if "room_type" in self.fields:
            self.fields["room_type"].widget.attrs.update({"class": "form-select"})


class BlockForm(forms.ModelForm):
    class Meta:
        model = Block
        fields = ["name", "total_floors"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "name" in self.fields:
            self.fields["name"].widget.attrs.update({"class": "form-control"})
        if "total_floors" in self.fields:
            self.fields["total_floors"].widget.attrs.update({"class": "form-control"})


class AttendancePhotoUploadForm(forms.Form):
    photo = forms.ImageField(
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control form-control-sm", "style": "width:100%;"}
        )
    )


class MakeupSessionCreateForm(forms.ModelForm):
    session_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control", "step": "60"}),
    )
    end_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control", "step": "60"}),
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Reason for make-up class"}),
    )
    mode = forms.ChoiceField(
        choices=AttendanceSession.MODE_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    attendance_mode = forms.ChoiceField(
        choices=AttendanceSession.ATTENDANCE_MODE_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Attendance Mode",
    )
    notify_students = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Notify Students",
    )

    class Meta:
        model = AttendanceSession
        fields = [
            "course",
            "classroom",
            "session_label",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "course" in self.fields:
            self.fields["course"].empty_label = "Select a course"
            self.fields["course"].widget.attrs.update({"class": "form-select"})
        if "classroom" in self.fields:
            self.fields["classroom"].queryset = Classroom.objects.select_related("block").order_by(
                "block__name",
                "room_number",
            )
            self.fields["classroom"].empty_label = "Select a classroom"
            self.fields["classroom"].required = False
            self.fields["classroom"].widget.attrs.update({"class": "form-select"})
        if "session_label" in self.fields:
            self.fields["session_label"].required = False
            self.fields["session_label"].widget.attrs.update(
                {"class": "form-control", "placeholder": "Enter session label"}
            )

        if not getattr(self.instance, "pk", None):
            now = timezone.localtime(timezone.now())
            if not self.initial.get("session_date"):
                self.initial["session_date"] = now.date()
            if not self.initial.get("start_time"):
                self.initial["start_time"] = (
                    now.replace(second=0, microsecond=0) + timezone.timedelta(minutes=1)
                ).time()
            if not self.initial.get("end_time"):
                self.initial["end_time"] = (
                    now.replace(second=0, microsecond=0) + timezone.timedelta(minutes=61)
                ).time()

    def clean(self):
        cleaned = super().clean()
        course = cleaned.get("course")
        classroom = cleaned.get("classroom")
        date = cleaned.get("session_date")
        start = cleaned.get("start_time")
        end = cleaned.get("end_time")

        if date and start and end:
            if end <= start:
                raise forms.ValidationError("End time must be after start time.")
            tz = timezone.get_current_timezone()
            start_dt = timezone.make_aware(datetime.combine(date, start), tz)
            end_dt = timezone.make_aware(datetime.combine(date, end), tz)
            if start_dt < timezone.now():
                raise forms.ValidationError("Session time cannot be in the past.")

            if course is not None:
                dup = AttendanceSession.objects.filter(
                    course=course,
                    session_type=AttendanceSession.TYPE_MAKEUP,
                    session_start_at__lt=end_dt,
                ).filter(
                    Q(session_end_at__gt=start_dt)
                    | Q(session_end_at__isnull=True, session_start_at__gt=start_dt)
                )
                if getattr(self.instance, "pk", None):
                    dup = dup.exclude(pk=self.instance.pk)
                if dup.exists():
                    conflict = dup.order_by("session_start_at").first()
                    if conflict is not None:
                        c_start = timezone.localtime(getattr(conflict, "session_start_at", start_dt))
                        c_end_raw = getattr(conflict, "session_end_at", None)
                        c_end = timezone.localtime(c_end_raw) if c_end_raw else None
                        window = (
                            f"{c_start.strftime('%Y-%m-%d %H:%M')}"
                            + (f" to {c_end.strftime('%H:%M')}" if c_end else "")
                        )
                        raise forms.ValidationError(
                            f"A make-up session for this course overlaps with the selected time range (existing: {window})."
                        )
                    raise forms.ValidationError(
                        "A make-up session for this course overlaps with the selected time range."
                    )

            if classroom is not None:
                busy = AttendanceSession.objects.filter(
                    classroom=classroom,
                    session_start_at__lt=end_dt,
                ).filter(
                    Q(session_end_at__gt=start_dt) | Q(session_end_at__isnull=True, session_start_at__gt=start_dt)
                )
                if getattr(self.instance, "pk", None):
                    busy = busy.exclude(pk=self.instance.pk)
                if busy.exists():
                    raise forms.ValidationError(
                        "Selected classroom is busy during this time range."
                    )
        return cleaned

    def save(self, commit=True):
        obj: AttendanceSession = super().save(commit=False)

        date = self.cleaned_data.get("session_date")
        start = self.cleaned_data.get("start_time")
        end = self.cleaned_data.get("end_time")
        tz = timezone.get_current_timezone()

        if date is not None and start is not None:
            start_dt = timezone.make_aware(datetime.combine(date, start), tz)
            obj.session_start_at = start_dt
            local_dt = timezone.localtime(start_dt)
            obj.session_date = local_dt.date()
            obj.time_slot = local_dt.strftime("%H:%M")

        if date is not None and end is not None:
            obj.session_end_at = timezone.make_aware(datetime.combine(date, end), tz)

        obj.reason = self.cleaned_data.get("reason") or ""
        obj.mode = self.cleaned_data.get("mode") or ""
        obj.attendance_mode = self.cleaned_data.get("attendance_mode") or ""
        obj.notify_students = bool(self.cleaned_data.get("notify_students"))

        if commit:
            obj.save()
            self.save_m2m()
        return obj


class RemedialCodeEntryForm(forms.Form):
    code = forms.CharField(
        max_length=16,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Enter remedial code"}
        ),
    )


class StudentForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = Student
        fields = ["roll_no", "full_name", "email", "parent_email", "parent_phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None or getattr(self.instance, "pk", None) is None:
            self.fields["password"].required = True
        self.fields["password"].widget.attrs.update({"placeholder": "Set student login password"})
        if "roll_no" in self.fields:
            self.fields["roll_no"].widget.attrs.update(
                {"class": "form-control", "placeholder": "e.g. CSE111023"}
            )
        if "full_name" in self.fields:
            self.fields["full_name"].widget.attrs.update(
                {"class": "form-control", "placeholder": "Enter full name"}
            )
        if "email" in self.fields:
            self.fields["email"].widget.attrs.update(
                {"class": "form-control", "placeholder": "Enter email address"}
            )
        if "parent_email" in self.fields:
            self.fields["parent_email"].widget.attrs.update(
                {"class": "form-control", "placeholder": "Enter parent's email address"}
            )
        if "parent_phone" in self.fields:
            self.fields["parent_phone"].widget.attrs.update(
                {"class": "form-control", "placeholder": "Enter parent's phone number"}
            )

    def save(self, commit=True):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        password = (self.cleaned_data.get("password") or "").strip()
        student: Student = super().save(commit=False)

        if commit:
            student.save()
            self.save_m2m()

        if student.uid is None:
            return student

        User = get_user_model()
        username = str(student.uid)

        user = student.user
        if user is None:
            user = User.objects.filter(username=username).first()
        if user is None:
            user = User(username=username)

        if getattr(user, "username", "") != username:
            user.username = username

        if getattr(student, "email", ""):
            user.email = student.email

        if password:
            user.set_password(password)

        user.save()

        group, _ = Group.objects.get_or_create(name="STUDENT")
        try:
            user.groups.add(group)
        except Exception:
            pass

        if student.user_id != user.id:
            student.user = user
            student.save(update_fields=["user"])

        return student


class EnrollmentForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = ["student", "course"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "student" in self.fields:
            self.fields["student"].widget.attrs.update({"class": "form-select"})
        if "course" in self.fields:
            self.fields["course"].widget.attrs.update({"class": "form-select"})


class FaceSampleForm(forms.ModelForm):
    class Meta:
        model = FaceSample
        fields = ["student", "image"]


class FaceSampleMultiForm(forms.Form):
    student = forms.ModelChoiceField(queryset=Student.objects.order_by("roll_no"))
    images = MultipleFileField(
        required=True,
        widget=MultipleFileInput(
            attrs={"multiple": True, "class": "form-control", "accept": "image/*"}
        ),
    )

    def clean_images(self):
        files = self.files.getlist("images")
        if len(files) < 5:
            raise forms.ValidationError("Please upload at least 5 photos.")
        if len(files) > 10:
            raise forms.ValidationError("Please upload at most 10 photos.")
        return files

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "student" in self.fields:
            self.fields["student"].widget.attrs.update({"class": "form-select"})
