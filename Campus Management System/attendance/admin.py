from django.contrib import admin

from .models import AttendanceRecord, AttendanceSession, Course, Enrollment, FaceSample, Notification, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("roll_no", "full_name", "email", "parent_phone")
    search_fields = ("roll_no", "full_name", "email")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course")
    list_filter = ("course",)
    search_fields = ("student__roll_no", "student__full_name", "course__code")


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("course", "session_start_at", "session_label", "created_at")
    list_filter = ("course", "session_start_at")


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
