from django.conf import settings
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone


class Subject(models.Model):
    name = models.CharField(max_length=128)
    code = models.CharField(max_length=32, unique=True)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Student(models.Model):
    UID_START = 12311000

    roll_no = models.CharField(max_length=32, unique=True)
    uid = models.BigIntegerField(unique=True, null=True, blank=True, db_index=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_student",
    )
    full_name = models.CharField(max_length=128)
    email = models.EmailField(blank=True)
    parent_email = models.EmailField(blank=True)
    parent_phone = models.CharField(max_length=32, blank=True)

    def __str__(self) -> str:
        return f"{self.roll_no} - {self.full_name}"

    def save(self, *args, **kwargs):
        if self.uid is None:
            with transaction.atomic():
                max_uid = Student.objects.aggregate(m=Max("uid")).get("m")
                next_uid = (int(max_uid) + 1) if max_uid is not None else self.UID_START
                self.uid = next_uid
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)


class AttendanceSession(models.Model):
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True)
    classroom = models.ForeignKey(
        "classrooms.Classroom",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    block = models.CharField(max_length=32, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    session_start_at = models.DateTimeField(default=timezone.now)
    session_date = models.DateField()
    time_slot = models.CharField(max_length=32, blank=True)
    session_label = models.CharField(max_length=64, blank=True)

    def __str__(self) -> str:
        label = self.session_label or "Session"
        return f"{self.course.code} {label} {self.session_start_at}".strip()

    def save(self, *args, **kwargs):
        # Auto-populate block and capacity from classroom if not set
        if self.classroom and not self.block:
            self.block = getattr(self.classroom.block, "name", "")
        if self.classroom and self.capacity is None:
            self.capacity = self.classroom.capacity
        super().save(*args, **kwargs)


class AttendanceRecord(models.Model):
    STATUS_PRESENT = "present"
    STATUS_ABSENT = "absent"

    STATUS_CHOICES = [
        (STATUS_PRESENT, "Present"),
        (STATUS_ABSENT, "Absent"),
    ]

    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    updated_at = models.DateTimeField(auto_now=True)
    source = models.CharField(max_length=32, default="manual")

    class Meta:
        unique_together = ("session", "student")

    def __str__(self) -> str:
        return f"{self.session_id} {self.student.roll_no} {self.status}"


class Notification(models.Model):
    recipient_student = models.ForeignKey(Student, on_delete=models.CASCADE)
    channel = models.CharField(max_length=32, default="simulated")
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.recipient_student.roll_no} {self.channel}"


def face_sample_upload_to(instance: "FaceSample", filename: str) -> str:
    return f"faces/{instance.student.roll_no}/{filename}"


class FaceSample(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    image = models.ImageField(upload_to=face_sample_upload_to)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.student.roll_no} sample"
