from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("attendance/", views.attendance_home, name="attendance_home"),
    path("manage/", views.manage_dashboard, name="manage_dashboard"),
    path("manage/students/", views.manage_students, name="manage_students"),
    path("manage/students/new/", views.manage_student_create, name="manage_student_create"),
    path("manage/students/<int:student_id>/edit/", views.manage_student_edit, name="manage_student_edit"),
    path("manage/students/<int:student_id>/delete/", views.manage_student_delete, name="manage_student_delete"),
    path("manage/courses/", views.manage_courses, name="manage_courses"),
    path("manage/courses/new/", views.manage_course_create, name="manage_course_create"),
    path("manage/courses/<int:course_id>/delete/", views.manage_course_delete, name="manage_course_delete"),
    path("manage/enrollments/", views.manage_enrollments, name="manage_enrollments"),
    path("manage/enrollments/new/", views.manage_enrollment_create, name="manage_enrollment_create"),
    path("manage/face-samples/", views.manage_face_samples, name="manage_face_samples"),
    path("manage/face-samples/new/", views.manage_face_sample_create, name="manage_face_sample_create"),
    path(
        "manage/face-samples/delete-all/",
        views.manage_face_samples_delete_all,
        name="manage_face_samples_delete_all",
    ),
    path(
        "manage/face-samples/<int:face_sample_id>/delete/",
        views.manage_face_sample_delete,
        name="manage_face_sample_delete",
    ),
    path("manage/notifications/", views.manage_notifications, name="manage_notifications"),
    path("manage/sessions/", views.manage_sessions, name="manage_sessions"),
    path("manage/records/", views.manage_records, name="manage_records"),
    path("faculty/sessions/new/", views.create_session, name="create_session"),
    path(
        "faculty/sessions/<int:session_id>/edit/",
        views.edit_session,
        name="edit_session",
    ),
    path(
        "faculty/sessions/<int:session_id>/delete/",
        views.delete_session,
        name="delete_session",
    ),
    path(
        "faculty/sessions/<int:session_id>/",
        views.session_detail,
        name="session_detail",
    ),
    path(
        "faculty/sessions/<int:session_id>/live/",
        views.live_attendance_frame,
        name="live_attendance_frame",
    ),
    path(
        "faculty/sessions/<int:session_id>/mark-by-photo/",
        views.mark_attendance_by_photo,
        name="mark_attendance_by_photo",
    ),
    path(
        "faculty/sessions/<int:session_id>/mark/",
        views.mark_attendance,
        name="mark_attendance",
    ),
]
