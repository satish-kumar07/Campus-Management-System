from django import forms
from django.utils import timezone

from courses.models import Course, Enrollment

from .models import AttendanceSession, FaceSample, Student


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
        fields = ["course", "session_start_at", "session_label"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("session_start_at") and not getattr(self.instance, "pk", None):
            now = timezone.localtime(timezone.now())
            now = (now.replace(second=0, microsecond=0) + timezone.timedelta(minutes=1))
            self.initial["session_start_at"] = now
        if "session_label" in self.fields:
            self.fields["session_label"].widget.attrs.update(
                {"class": "form-control", "placeholder": "Enter session label"}
            )
        if "course" in self.fields:
            self.fields["course"].empty_label = "Select a course"
            self.fields["course"].widget.attrs.update({"class": "form-select"})

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


class AttendancePhotoUploadForm(forms.Form):
    photo = forms.ImageField(
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control form-control-sm", "style": "width:100%;"}
        )
    )


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["roll_no", "full_name", "email", "parent_email", "parent_phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
