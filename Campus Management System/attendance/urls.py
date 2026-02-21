from django.urls import path

from . import views
from .authz import require_teacher

urlpatterns = [
    path("", require_teacher(views.home), name="home"),
    path("attendance/", require_teacher(views.attendance_home), name="attendance_home"),
    path("manage/", require_teacher(views.manage_dashboard), name="manage_dashboard"),
    path("manage/students/", require_teacher(views.manage_students), name="manage_students"),
    path("manage/students/new/", require_teacher(views.manage_student_create), name="manage_student_create"),
    path("manage/students/<int:student_id>/edit/", require_teacher(views.manage_student_edit), name="manage_student_edit"),
    path("manage/students/<int:student_id>/delete/", require_teacher(views.manage_student_delete), name="manage_student_delete"),
    path("manage/courses/", require_teacher(views.manage_courses), name="manage_courses"),
    path("manage/courses/new/", require_teacher(views.manage_course_create), name="manage_course_create"),
    path("manage/courses/<int:course_id>/delete/", require_teacher(views.manage_course_delete), name="manage_course_delete"),
    path("manage/enrollments/", require_teacher(views.manage_enrollments), name="manage_enrollments"),
    path("manage/enrollments/new/", require_teacher(views.manage_enrollment_create), name="manage_enrollment_create"),
    path("manage/face-samples/", require_teacher(views.manage_face_samples), name="manage_face_samples"),
    path("manage/face-samples/new/", require_teacher(views.manage_face_sample_create), name="manage_face_sample_create"),
    path(
        "manage/face-samples/delete-all/",
        require_teacher(views.manage_face_samples_delete_all),
        name="manage_face_samples_delete_all",
    ),
    path(
        "manage/face-samples/<int:face_sample_id>/delete/",
        require_teacher(views.manage_face_sample_delete),
        name="manage_face_sample_delete",
    ),
    path("manage/notifications/", require_teacher(views.manage_notifications), name="manage_notifications"),
    path("manage/sessions/", require_teacher(views.manage_sessions), name="manage_sessions"),
    path("manage/records/", require_teacher(views.manage_records), name="manage_records"),
    path("faculty/sessions/new/", require_teacher(views.create_session), name="create_session"),
    path(
        "faculty/sessions/<int:session_id>/edit/",
        require_teacher(views.edit_session),
        name="edit_session",
    ),
    path(
        "faculty/sessions/<int:session_id>/delete/",
        require_teacher(views.delete_session),
        name="delete_session",
    ),
    path(
        "faculty/sessions/<int:session_id>/",
        require_teacher(views.session_detail),
        name="session_detail",
    ),
    path(
        "faculty/sessions/<int:session_id>/live/",
        require_teacher(views.live_attendance_frame),
        name="live_attendance_frame",
    ),
    path(
        "faculty/sessions/<int:session_id>/mark-by-photo/",
        require_teacher(views.mark_attendance_by_photo),
        name="mark_attendance_by_photo",
    ),
    path(
        "faculty/sessions/<int:session_id>/mark/",
        require_teacher(views.mark_attendance),
        name="mark_attendance",
    ),
]
