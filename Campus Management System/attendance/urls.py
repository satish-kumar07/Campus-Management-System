from django.urls import path

from . import views
from .authz import require_teacher

urlpatterns = [
    path("", require_teacher(views.home), name="home"),
    path("attendance/", require_teacher(views.attendance_home), name="attendance_home"),
    path("faculty/", require_teacher(views.faculty_dashboard), name="faculty_dashboard"),
    path(
        "faculty/courses/<int:course_id>/students/",
        require_teacher(views.faculty_course_students),
        name="faculty_course_students",
    ),
    path(
        "faculty/courses/<int:course_id>/sessions/",
        require_teacher(views.faculty_course_sessions),
        name="faculty_course_sessions",
    ),
    path(
        "faculty/courses/<int:course_id>/take/",
        require_teacher(views.take_attendance),
        name="take_attendance",
    ),
    path(
        "faculty/attendance/confirmation/<int:session_id>/",
        require_teacher(views.attendance_confirmation),
        name="attendance_confirmation",
    ),
    path("manage/", require_teacher(views.manage_dashboard), name="manage_dashboard"),
    path("manage/students/", require_teacher(views.manage_students), name="manage_students"),
    path("manage/students/new/", require_teacher(views.manage_student_create), name="manage_student_create"),
    path("manage/students/<int:student_id>/edit/", require_teacher(views.manage_student_edit), name="manage_student_edit"),
    path("manage/students/<int:student_id>/delete/", require_teacher(views.manage_student_delete), name="manage_student_delete"),
    path("manage/courses/", require_teacher(views.manage_courses), name="manage_courses"),
    path("manage/courses/new/", require_teacher(views.manage_course_create), name="manage_course_create"),
    path("manage/courses/<int:course_id>/edit/", require_teacher(views.manage_course_edit), name="manage_course_edit"),
    path("manage/courses/<int:course_id>/delete/", require_teacher(views.manage_course_delete), name="manage_course_delete"),
    path("manage/enrollments/", require_teacher(views.manage_enrollments), name="manage_enrollments"),
    path("manage/enrollments/new/", require_teacher(views.manage_enrollment_create), name="manage_enrollment_create"),
    path("manage/faculty/", require_teacher(views.manage_faculty), name="manage_faculty"),
    path("manage/faculty/new/", require_teacher(views.manage_faculty_create), name="manage_faculty_create"),
    path("manage/faculty/<int:faculty_id>/edit/", require_teacher(views.manage_faculty_edit), name="manage_faculty_edit"),
    path("manage/faculty/<int:faculty_id>/delete/", require_teacher(views.manage_faculty_delete), name="manage_faculty_delete"),
    path("manage/blocks/", require_teacher(views.manage_blocks), name="manage_blocks"),
    path("manage/blocks/new/", require_teacher(views.manage_block_create), name="manage_block_create"),
    path("manage/blocks/<int:block_id>/edit/", require_teacher(views.manage_block_edit), name="manage_block_edit"),
    path("manage/blocks/<int:block_id>/delete/", require_teacher(views.manage_block_delete), name="manage_block_delete"),
    path("manage/classrooms/", require_teacher(views.manage_classrooms), name="manage_classrooms"),
    path("manage/classrooms/new/", require_teacher(views.manage_classroom_create), name="manage_classroom_create"),
    path("manage/classrooms/<int:classroom_id>/edit/", require_teacher(views.manage_classroom_edit), name="manage_classroom_edit"),
    path("manage/classrooms/<int:classroom_id>/delete/", require_teacher(views.manage_classroom_delete), name="manage_classroom_delete"),
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
        "faculty/sessions/<int:session_id>/manual/",
        require_teacher(views.session_manual),
        name="session_manual",
    ),
    path(
        "faculty/sessions/<int:session_id>/face/",
        require_teacher(views.session_face),
        name="session_face",
    ),
    path(
        "faculty/sessions/<int:session_id>/history/",
        require_teacher(views.session_history),
        name="session_history",
    ),
    path(
        "faculty/sessions/<int:session_id>/summary/",
        require_teacher(views.session_mark_summary),
        name="session_mark_summary",
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
    path(
        "faculty/sessions/<int:session_id>/mark-choice/",
        require_teacher(views.mark_attendance_choice),
        name="mark_attendance_choice",
    ),
]
