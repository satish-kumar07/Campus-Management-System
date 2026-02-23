from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import BooleanField, Case, Count, F, FloatField, Sum, Value, When, Q
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from datetime import datetime

import random
import string

import logging

import cv2
import numpy as np
from PIL import Image
from django.http import JsonResponse
import base64
import time
from collections import deque

from faculty.models import Faculty

from classrooms.models import Classroom

from food_ordering.models import FoodStall, MenuCategory, MenuItem


User = get_user_model()

from .face_recognition import (
    build_training_set,
    detect_eyes_count,
    detect_faces_count,
    recognize_faces_in_image,
    train_lbph,
)
from .forms import (
    AttendancePhotoUploadForm,
    AttendanceSessionCreateForm,
    MakeupSessionCreateForm,
    VendorCreateForm,
    FoodStallManageForm,
    MenuCategoryManageForm,
    MenuItemManageForm,
    RemedialCodeEntryForm,
    CourseCreateForm,
    EnrollmentForm,
    FacultyForm,
    FaceSampleMultiForm,
    FaceSampleForm,
    ClassroomForm,
    BlockForm,
    StudentForm,
)
from courses.models import Course, Enrollment

from .models import AttendanceRecord, AttendanceSession, FaceSample, Notification, Student

from blocks.models import Block

from .authz import require_teacher
from .authz import require_student


_live_state: dict[tuple[int, int], dict[str, object]] = {}

logger = logging.getLogger(__name__)


def _format_ago(dt) -> str:
    try:
        delta = timezone.now() - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        mins = secs // 60
        if mins < 60:
            return f"{mins} min ago"
        hrs = mins // 60
        if hrs < 24:
            return f"{hrs} hr ago"
        days = hrs // 24
        return f"{days} day ago" if days == 1 else f"{days} days ago"
    except Exception:
        return "-"


def _student_course_ids(student: Student) -> list[int]:
    return list(Enrollment.objects.filter(student=student).values_list("course_id", flat=True))


def _student_attendance_stats(*, student: Student, course_ids: list[int]) -> dict[str, object]:
    courses_count = int(len(course_ids))
    overall_attendance_pct = 0
    below_threshold_courses = 0

    total_sessions = 0
    present = 0
    absent = 0
    pending = 0

    if course_ids:
        now = timezone.now()
        session_types = [AttendanceSession.TYPE_REGULAR, AttendanceSession.TYPE_MAKEUP]
        regular_qs = AttendanceSession.objects.filter(
            course_id__in=course_ids,
            session_type__in=session_types,
            session_start_at__lte=now,
        )

        total_sessions = regular_qs.count()
        present = AttendanceRecord.objects.filter(
            student=student,
            session__course_id__in=course_ids,
            session__session_type__in=session_types,
            session__session_start_at__lte=now,
            status=AttendanceRecord.STATUS_PRESENT,
        ).count()
        absent = AttendanceRecord.objects.filter(
            student=student,
            session__course_id__in=course_ids,
            session__session_type__in=session_types,
            session__session_start_at__lte=now,
            status=AttendanceRecord.STATUS_ABSENT,
        ).count()

        taken = int(present) + int(absent)
        pending = max(int(total_sessions) - int(taken), 0)

        denom = int(total_sessions)
        if denom > 0:
            overall_attendance_pct = int(round((int(present) / float(denom)) * 100.0))

        threshold = 75
        below = 0
        for cid in course_ids:
            total_c = AttendanceSession.objects.filter(
                course_id=cid,
                session_type__in=session_types,
                session_start_at__lte=now,
            ).count()
            present_c = AttendanceRecord.objects.filter(
                student=student,
                session__course_id=cid,
                session__session_type__in=session_types,
                session__session_start_at__lte=now,
                status=AttendanceRecord.STATUS_PRESENT,
            ).count()
            absent_c = AttendanceRecord.objects.filter(
                student=student,
                session__course_id=cid,
                session__session_type__in=session_types,
                session__session_start_at__lte=now,
                status=AttendanceRecord.STATUS_ABSENT,
            ).count()
            taken_c = int(present_c) + int(absent_c)
            denom_c = int(total_c)
            pct_c = int(round((int(present_c) / float(denom_c)) * 100.0)) if denom_c > 0 else 0
            if pct_c < threshold:
                below += 1
        below_threshold_courses = int(below)

    return {
        "courses_count": int(courses_count),
        "overall_attendance_pct": int(overall_attendance_pct),
        "below_threshold_courses": int(below_threshold_courses),
        "total_sessions": int(total_sessions),
        "present": int(present),
        "absent": int(absent),
        "taken": int(int(present) + int(absent)),
        "pending": int(pending),
    }


def _generate_remedial_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(8))


def _unique_remedial_code() -> str:
    for _ in range(20):
        code = _generate_remedial_code()
        if not AttendanceSession.objects.filter(remedial_code=code).exists():
            return code
    return _generate_remedial_code()


def _session_counts(*, session: AttendanceSession) -> dict[str, int]:
    students_qs = (
        Student.objects.filter(course_enrollments__course=session.course)
        .order_by("roll_no")
        .distinct()
    )
    total = students_qs.count()
    present = AttendanceRecord.objects.filter(
        session=session, status=AttendanceRecord.STATUS_PRESENT
    ).count()
    absent = AttendanceRecord.objects.filter(
        session=session, status=AttendanceRecord.STATUS_ABSENT
    ).count()
    marked = present + absent
    unmarked = max(total - marked, 0)
    return {
        "total": int(total),
        "present": int(present),
        "absent": int(absent),
        "unmarked": int(unmarked),
        "marked": int(marked),
    }


def _session_is_completed(*, session: AttendanceSession) -> bool:
    c = _session_counts(session=session)
    return bool(c["total"] > 0 and c["marked"] >= c["total"])


def _send_absent_email(*, student: Student, session: AttendanceSession) -> tuple[bool, str]:
    recipients: list[str] = []
    parent_email = (getattr(student, "parent_email", "") or "").strip()
    student_email = (getattr(student, "email", "") or "").strip()
    if parent_email:
        recipients.append(parent_email)
    if student_email:
        recipients.append(student_email)
    recipients = sorted({r for r in recipients if r})
    if not recipients:
        logger.info("Absent email not sent: missing recipient email for student_id=%s", student.id)
        return (False, "Missing parent/student email")
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
    if not from_email:
        logger.error("Absent email not sent: DEFAULT_FROM_EMAIL/EMAIL_HOST_USER not configured")
        return (False, "Email not configured (DEFAULT_FROM_EMAIL/EMAIL_HOST_USER)")
    uid = getattr(student, "uid", "")
    uid_str = str(uid) if uid is not None else ""
    course_code = getattr(getattr(session, "course", None), "code", "")
    course_name = getattr(getattr(session, "course", None), "name", "")
    start_at = getattr(session, "session_start_at", None)
    date_str = start_at.strftime("%Y-%m-%d") if start_at else str(getattr(session, "session_date", ""))
    time_str = start_at.strftime("%H:%M") if start_at else (getattr(session, "time_slot", "") or "")
    room = getattr(getattr(session, "classroom", None), "room_number", "")
    label = getattr(session, "session_label", "") or ""

    subject = f"Attendance Notice: Absent - {student.full_name} ({course_code})"

    body = "Dear Parent/Guardian and Student,\n\n"
    body += "This is an official attendance notification from the College Attendance Management System.\n\n"
    body += "Student Details:\n"
    body += f"- Name: {student.full_name}\n"
    body += f"- UID: {uid_str}\n"
    body += f"- Roll No: {student.roll_no}\n\n"
    body += "Session Details:\n"
    body += f"- Course: {course_code}"
    if course_name:
        body += f" - {course_name}"
    body += "\n"
    body += f"- Date: {date_str}\n"
    if time_str:
        body += f"- Time: {time_str}\n"
    if room:
        body += f"- Room: {room}\n"
    if label:
        body += f"- Session: {label}\n"

    body += "\nStatus: ABSENT\n\n"
    body += "If you believe this is incorrect, please contact the course instructor or the academic office within 24 hours.\n\n"
    body += "Regards,\nAttendance Office\n"
    try:
        msg = EmailMessage(subject=subject, body=body, from_email=from_email, to=recipients)
        msg.send(fail_silently=False)
        return (True, "")
    except Exception as e:
        logger.exception(
            "Absent email send failed for student_id=%s session_id=%s recipients=%s",
            student.id,
            session.id,
            recipients,
        )
        detail = f"{type(e).__name__}: {e}".strip()
        return (False, f"SMTP send failed ({detail})")


def _live_key(request: HttpRequest, session_id: int) -> tuple[int, int]:
    return (int(request.user.id or 0), int(session_id))


def _live_get_state(request: HttpRequest, session_id: int) -> dict[str, object]:
    key = _live_key(request, session_id)
    st = _live_state.get(key)
    if st is None:
        st = {
            "last_ts": 0.0,
            "eyes": deque(maxlen=8),
            "last_blink_ts": 0.0,
            "candidates": {},
        }
        _live_state[key] = st
    return st


def _blink_seen(state: dict[str, object]) -> bool:
    eyes: deque[int] = state["eyes"]  # type: ignore[assignment]
    if len(eyes) < 3:
        return False
    vals = list(eyes)
    hi1 = any(v >= 1 for v in vals[:2])
    low = any(v == 0 for v in vals[2:5])
    hi2 = any(v >= 1 for v in vals[5:]) if len(vals) >= 6 else any(v >= 1 for v in vals[4:])
    return bool(hi1 and low and hi2)


@login_required
@require_teacher
def home(request: HttpRequest) -> HttpResponse:
    recent_sessions = AttendanceSession.objects.select_related("course").order_by("-created_at")[:3]
    stats = {
        "students": Student.objects.count(),
        "courses": Course.objects.count(),
        "enrollments": Enrollment.objects.count(),
        "face_samples": FaceSample.objects.count(),
        "sessions": AttendanceSession.objects.count(),
    }

    now_dt = timezone.now()
    upcoming_qs = AttendanceSession.objects.select_related("course").filter(session_start_at__gt=now_dt)
    upcoming_sessions = list(upcoming_qs.order_by("session_start_at")[:6])
    active_now_count = AttendanceSession.objects.filter(session_start_at__lte=now_dt).filter(
        Q(session_end_at__gte=now_dt) | Q(session_end_at__isnull=True)
    ).count()
    makeup_pending_count = AttendanceSession.objects.filter(session_type=AttendanceSession.TYPE_MAKEUP).filter(
        Q(session_end_at__gt=now_dt) | Q(session_end_at__isnull=True, session_start_at__gt=now_dt)
    ).count()

    util_qs = AttendanceSession.objects.filter(classroom__isnull=False, classroom__capacity__gt=0)
    classroom_utilization = list(
        util_qs.values(
            "classroom_id",
            "classroom__room_number",
            "classroom__block__name",
            "classroom__capacity",
        )
        .annotate(
            sessions_count=Count("id"),
            records_count=Count("attendancerecord"),
        )
        .annotate(
            utilization_pct=(
                100.0
                * F("records_count")
                / Coalesce((F("sessions_count") * F("classroom__capacity")), 1)
            )
        )
        .order_by("-utilization_pct")[:8]
    )

    block_utilization = list(
        util_qs.values("classroom__block__name")
        .annotate(
            sessions_count=Count("id"),
            records_count=Count("attendancerecord"),
            seats_offered=Sum("classroom__capacity"),
        )
        .annotate(utilization_pct=(100.0 * F("records_count") / Coalesce(F("seats_offered"), 1)))
        .order_by("-utilization_pct")[:6]
    )
    return render(
        request,
        "attendance/dashboard.html",
        {
            "recent_sessions": recent_sessions,
            "stats": stats,
            "makeup_pending": int(makeup_pending_count),
            "upcoming_count": int(upcoming_qs.count()),
            "active_now": int(active_now_count),
            "upcoming_sessions": upcoming_sessions,
            "classroom_utilization": classroom_utilization,
            "block_utilization": block_utilization,
        },
    )


@login_required
@require_teacher
def attendance_home(request: HttpRequest) -> HttpResponse:
    user = getattr(request, "user", None)
    email = (getattr(user, "email", "") or "").strip().lower()
    faculty = Faculty.objects.filter(email__iexact=email).first() if email else None

    allowed_courses = Course.objects.order_by("code")
    if faculty is not None:
        allowed_courses = allowed_courses.filter(faculty=faculty)

    now_dt = timezone.now()

    base_qs = (
        AttendanceSession.objects.select_related("course")
        .filter(course__in=allowed_courses)
        .annotate(
            present_count=Count(
                "attendancerecord",
                filter=Q(attendancerecord__status=AttendanceRecord.STATUS_PRESENT),
            ),
            absent_count=Count(
                "attendancerecord",
                filter=Q(attendancerecord__status=AttendanceRecord.STATUS_ABSENT),
            ),
            total_count=Count("attendancerecord"),
            enrolled_count=Count("course__enrollments", distinct=True),
        )
        .annotate(
            is_completed=Case(
                When(
                    enrolled_count__gt=0,
                    total_count__gte=F("enrolled_count"),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
    )

    pending_sessions = list(
        base_qs.filter(session_start_at__lte=now_dt)
        .filter(is_completed=False)
        .order_by("session_start_at")[:15]
    )

    upcoming_sessions = list(
        base_qs.filter(session_start_at__gt=now_dt)
        .exclude(session_type=AttendanceSession.TYPE_MAKEUP)
        .order_by("session_start_at")[:15]
    )

    makeup_sessions = list(
        base_qs.filter(session_type=AttendanceSession.TYPE_MAKEUP)
        .filter(Q(session_end_at__gt=now_dt) | Q(session_end_at__isnull=True, session_start_at__gt=now_dt))
        .order_by("session_start_at")[:15]
    )

    recent_sessions = list(base_qs.order_by("-created_at")[:20])

    return render(
        request,
        "attendance/attendance_home.html",
        {
            "faculty": faculty,
            "now_dt": now_dt,
            "pending_sessions": pending_sessions,
            "upcoming_sessions": upcoming_sessions,
            "makeup_sessions": makeup_sessions,
            "sessions": recent_sessions,
        },
    )


@login_required
@require_student
def student_dashboard(request: HttpRequest) -> HttpResponse:
    student = Student.objects.filter(user=request.user).first()
    if student is None:
        messages.error(request, "Student profile not linked. Contact admin.")

    stats = {
        "courses_count": 0,
        "overall_attendance_pct": 0,
        "below_threshold_courses": 0,
        "total_sessions": 0,
        "present": 0,
        "absent": 0,
        "taken": 0,
    }
    makeup_pending = 0
    next_session = None
    recent_notifications = []

    if student is not None:
        course_ids = _student_course_ids(student)
        stats = _student_attendance_stats(student=student, course_ids=course_ids)

        now = timezone.now()
        if course_ids:
            next_session = (
                AttendanceSession.objects.select_related("course", "classroom")
                .filter(course_id__in=course_ids, session_start_at__gte=now)
                .order_by("session_start_at")
                .first()
            )

            makeup_qs = AttendanceSession.objects.filter(
                course_id__in=course_ids,
                session_type=AttendanceSession.TYPE_MAKEUP,
            )
            makeup_qs = makeup_qs.filter(
                Q(remedial_expires_at__isnull=True) | Q(remedial_expires_at__gte=now)
            )
            makeup_qs = makeup_qs.exclude(
                attendancerecord__student=student,
            )
            makeup_pending = int(makeup_qs.count())

        recent_notifications = list(
            Notification.objects.filter(recipient_student=student)
            .order_by("-created_at")[:6]
        )

    return render(
        request,
        "attendance/student_dashboard.html",
        {
            "student": student,
            "courses_count": stats.get("courses_count", 0),
            "overall_attendance_pct": stats.get("overall_attendance_pct", 0),
            "below_threshold_courses": stats.get("below_threshold_courses", 0),
            "present": stats.get("present", 0),
            "absent": stats.get("absent", 0),
            "pending": stats.get("pending", 0),
            "makeup_pending": makeup_pending,
            "next_session": next_session,
            "recent_notifications": recent_notifications,
        },
    )


@login_required
@require_student
def student_live_stats(request: HttpRequest) -> JsonResponse:
    student = Student.objects.filter(user=request.user).first()
    if student is None:
        return JsonResponse({"ok": False, "error": "Student profile not linked."}, status=400)

    course_ids = _student_course_ids(student)
    stats = _student_attendance_stats(student=student, course_ids=course_ids)

    now = timezone.now()
    next_session = None
    if course_ids:
        next_session = (
            AttendanceSession.objects.select_related("course", "classroom")
            .filter(course_id__in=course_ids, session_start_at__gte=now)
            .order_by("session_start_at")
            .first()
        )

    makeup_pending = 0
    if course_ids:
        makeup_qs = AttendanceSession.objects.filter(
            course_id__in=course_ids,
            session_type=AttendanceSession.TYPE_MAKEUP,
        )
        makeup_qs = makeup_qs.filter(
            Q(remedial_expires_at__isnull=True) | Q(remedial_expires_at__gte=now)
        )
        makeup_qs = makeup_qs.exclude(attendancerecord__student=student)
        makeup_pending = int(makeup_qs.count())

    notifs = list(
        Notification.objects.filter(recipient_student=student)
        .order_by("-created_at")[:6]
    )
    notif_payload = [
        {
            "id": int(n.id),
            "message": str(n.message or ""),
            "ago": _format_ago(getattr(n, "created_at", now)),
        }
        for n in notifs
    ]

    next_payload = None
    if next_session is not None:
        try:
            start_label = timezone.localtime(next_session.session_start_at).strftime("%I:%M %p").lstrip("0")
        except Exception:
            start_label = "-"
        room = "-"
        try:
            if getattr(next_session, "classroom", None) is not None:
                room = str(getattr(next_session.classroom, "room_number", "-") or "-")
        except Exception:
            room = "-"
        next_payload = {
            "course": str(getattr(getattr(next_session, "course", None), "code", "") or ""),
            "time": start_label,
            "room": room,
        }

    return JsonResponse(
        {
            "ok": True,
            "courses_count": int(stats.get("courses_count", 0)),
            "overall_attendance_pct": int(stats.get("overall_attendance_pct", 0)),
            "below_threshold_courses": int(stats.get("below_threshold_courses", 0)),
            "present": int(stats.get("present", 0)),
            "absent": int(stats.get("absent", 0)),
            "total_sessions": int(stats.get("total_sessions", 0)),
            "taken": int(stats.get("taken", 0)),
            "pending": int(stats.get("pending", 0)),
            "makeup_pending": int(makeup_pending),
            "next_session": next_payload,
            "notifications": notif_payload,
        }
    )


@login_required
@require_student
def student_attendance_details(request: HttpRequest) -> HttpResponse:
    student = Student.objects.filter(user=request.user).first()
    if student is None:
        messages.error(request, "Student profile not linked. Contact admin.")
        return redirect("student_dashboard")

    course_ids = _student_course_ids(student)
    stats = _student_attendance_stats(student=student, course_ids=course_ids)

    taken = int(stats.get("taken", 0) or 0)
    present = int(stats.get("present", 0) or 0)
    total = int(stats.get("total_sessions", 0) or 0)
    absent = int(stats.get("absent", 0) or 0)
    pending = max(int(total) - (int(present) + int(absent)), 0)

    present_deg = int(round((float(present) / float(total)) * 360.0)) if total > 0 else 0
    absent_deg = int(round((float(absent) / float(total)) * 360.0)) if total > 0 else 0
    pending_deg = max(360 - present_deg - absent_deg, 0) if total > 0 else 0

    per_course: list[dict[str, object]] = []
    threshold = 75
    now = timezone.now()
    session_types = [AttendanceSession.TYPE_REGULAR, AttendanceSession.TYPE_MAKEUP]
    for cid in course_ids:
        c = Course.objects.filter(id=cid).first()
        total_c = AttendanceSession.objects.filter(
            course_id=cid,
            session_type__in=session_types,
            session_start_at__lte=now,
        ).count()
        present_c = AttendanceRecord.objects.filter(
            student=student,
            session__course_id=cid,
            session__session_type__in=session_types,
            session__session_start_at__lte=now,
            status=AttendanceRecord.STATUS_PRESENT,
        ).count()
        absent_c = AttendanceRecord.objects.filter(
            student=student,
            session__course_id=cid,
            session__session_type__in=session_types,
            session__session_start_at__lte=now,
            status=AttendanceRecord.STATUS_ABSENT,
        ).count()
        taken_c = int(present_c) + int(absent_c)
        denom_c = int(total_c)
        pct_c = int(round((int(present_c) / float(denom_c)) * 100.0)) if denom_c > 0 else 0
        per_course.append(
            {
                "course": c,
                "total": int(total_c),
                "present": int(present_c),
                "absent": int(absent_c),
                "taken": int(taken_c),
                "pct": int(pct_c),
                "below": bool(int(pct_c) < int(threshold)),
            }
        )

    return render(
        request,
        "attendance/student_attendance_details.html",
        {
            "student": student,
            "stats": stats,
            "present_deg": present_deg,
            "absent_deg": absent_deg,
            "pending_deg": pending_deg,
            "pending": pending,
            "threshold": threshold,
            "per_course": per_course,
        },
    )


@login_required
@require_student
def student_courses(request: HttpRequest) -> HttpResponse:
    student = Student.objects.filter(user=request.user).first()
    if student is None:
        messages.error(request, "Student profile not linked. Contact admin.")
        return redirect("student_dashboard")

    now = timezone.now()
    session_types = [AttendanceSession.TYPE_REGULAR, AttendanceSession.TYPE_MAKEUP]

    enrollments = (
        Enrollment.objects.filter(student=student)
        .select_related("course", "course__faculty", "course__classroom")
        .order_by("course__code")
    )

    rows: list[dict[str, object]] = []
    for e in enrollments:
        c = getattr(e, "course", None)
        if c is None:
            continue

        total_sessions = AttendanceSession.objects.filter(
            course=c,
            session_type__in=session_types,
            session_start_at__lte=now,
        ).count()
        present = AttendanceRecord.objects.filter(
            student=student,
            session__course=c,
            session__session_type__in=session_types,
            session__session_start_at__lte=now,
            status=AttendanceRecord.STATUS_PRESENT,
        ).count()
        absent = AttendanceRecord.objects.filter(
            student=student,
            session__course=c,
            session__session_type__in=session_types,
            session__session_start_at__lte=now,
            status=AttendanceRecord.STATUS_ABSENT,
        ).count()
        taken = int(present) + int(absent)
        pending = max(int(total_sessions) - int(taken), 0)
        pct = int(round((int(present) / float(total_sessions)) * 100.0)) if int(total_sessions) > 0 else 0

        rows.append(
            {
                "course": c,
                "total_sessions": int(total_sessions),
                "present": int(present),
                "absent": int(absent),
                "pending": int(pending),
                "pct": int(pct),
            }
        )

    return render(
        request,
        "attendance/student_courses.html",
        {
            "student": student,
            "rows": rows,
        },
    )


@login_required
@require_student
def student_makeup_sessions(request: HttpRequest) -> HttpResponse:
    student = Student.objects.filter(user=request.user).first()
    if student is None:
        messages.error(request, "Student profile not linked. Contact admin.")
        return redirect("student_dashboard")

    now = timezone.now()

    sessions_qs = (
        AttendanceSession.objects.select_related("course", "classroom", "classroom__block")
        .filter(
            session_type=AttendanceSession.TYPE_MAKEUP,
            course__enrollments__student=student,
        )
        .order_by("-session_start_at")
        .distinct()
    )

    rows: list[dict[str, object]] = []
    for s in sessions_qs[:50]:
        start_at = getattr(s, "session_start_at", None)
        end_at = getattr(s, "session_end_at", None)
        expires_at = getattr(s, "remedial_expires_at", None)
        cutoff = None
        if end_at and expires_at:
            cutoff = min(end_at, expires_at)
        elif end_at:
            cutoff = end_at
        elif expires_at:
            cutoff = expires_at

        is_upcoming = bool(start_at and now < start_at)
        is_active = bool(start_at and cutoff and start_at <= now <= cutoff)
        is_expired = bool(cutoff and now > cutoff)

        marked = AttendanceRecord.objects.filter(session=s, student=student).exists()

        rows.append(
            {
                "session": s,
                "start_at": start_at,
                "end_at": end_at,
                "cutoff": cutoff,
                "is_upcoming": is_upcoming,
                "is_active": is_active,
                "is_expired": is_expired,
                "marked": bool(marked),
            }
        )

    pending_count = sum((1 for r in rows if not r.get("marked") and not r.get("is_expired")), 0)

    return render(
        request,
        "attendance/student_makeup_sessions.html",
        {
            "student": student,
            "rows": rows,
            "pending_count": int(pending_count),
        },
    )


@login_required
@require_teacher
def faculty_dashboard(request: HttpRequest) -> HttpResponse:
    user = getattr(request, "user", None)
    email = (getattr(user, "email", "") or "").strip().lower()
    faculty = None
    if email:
        faculty = Faculty.objects.filter(email__iexact=email).first()

    qs = Course.objects.order_by("code")
    if faculty is not None:
        qs = qs.filter(faculty=faculty)

    courses = list(qs)

    now_dt = timezone.now()
    today = timezone.localdate()
    week_start = today - timezone.timedelta(days=today.weekday())

    recent_sessions_qs = (
        AttendanceSession.objects.select_related("course")
        .annotate(
            present_count=Count(
                "attendancerecord",
                filter=Q(attendancerecord__status=AttendanceRecord.STATUS_PRESENT),
            ),
            absent_count=Count(
                "attendancerecord",
                filter=Q(attendancerecord__status=AttendanceRecord.STATUS_ABSENT),
            ),
            total_count=Count("attendancerecord"),
            enrolled_count=Count("course__enrollments", distinct=True),
        )
        .annotate(
            is_completed=Case(
                When(
                    enrolled_count__gt=0,
                    total_count__gte=F("enrolled_count"),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
        .order_by("-created_at")
    )
    if faculty is not None:
        recent_sessions_qs = recent_sessions_qs.filter(course__in=courses)
    recent_sessions = list(recent_sessions_qs[:10])

    sessions_total_qs = AttendanceSession.objects.all()
    if faculty is not None:
        sessions_total_qs = sessions_total_qs.filter(course__in=courses)
    sessions_total = sessions_total_qs.count()
    sessions_week = sessions_total_qs.filter(session_date__gte=week_start).count()

    # Students handled = unique enrolled students across faculty courses
    enrollments_qs = Enrollment.objects.all()
    if faculty is not None:
        enrollments_qs = enrollments_qs.filter(course__in=courses)
    students_handled = enrollments_qs.values("student_id").distinct().count()

    # Average attendance across recent sessions (avoid division by zero)
    records_qs = AttendanceRecord.objects.all()
    if faculty is not None:
        records_qs = records_qs.filter(session__course__in=courses)
    total_records = records_qs.count()
    present_records = records_qs.filter(status=AttendanceRecord.STATUS_PRESENT).count()
    avg_attendance_pct = round((present_records * 100.0 / total_records), 1) if total_records else 0.0

    # Alerts
    alerts: list[str] = []
    no_enrollment = [c.code for c in courses if not Enrollment.objects.filter(course=c).exists()]
    if no_enrollment:
        alerts.append(f"No enrollments for: {', '.join(no_enrollment[:5])}{'...' if len(no_enrollment) > 5 else ''}")

    # Face data missing: students enrolled but no face sample
    missing_face_courses: list[str] = []
    for c in courses[:50]:
        enrolled_ids = list(Enrollment.objects.filter(course=c).values_list("student_id", flat=True).distinct())
        if not enrolled_ids:
            continue
        face_ids = set(
            FaceSample.objects.filter(student_id__in=enrolled_ids).values_list("student_id", flat=True).distinct()
        )
        missing = [sid for sid in enrolled_ids if sid not in face_ids]
        if missing:
            missing_face_courses.append(f"{c.code}({len(missing)})")
    if missing_face_courses:
        alerts.append(
            "Face data missing for enrolled students in: "
            + ", ".join(missing_face_courses[:5])
            + ("..." if len(missing_face_courses) > 5 else "")
        )

    # Faculty workload distribution (based on assigned courses weekly_hours)
    faculty_rows = list(
        Faculty.objects.annotate(
            assigned_hours=Coalesce(Sum("course__weekly_hours"), 0),
        ).order_by("name")
    )
    faculty_workloads: list[dict[str, object]] = []
    counts = {"overloaded": 0, "balanced": 0, "underloaded": 0, "unassigned": 0}
    for fobj in faculty_rows:
        assigned = int(getattr(fobj, "assigned_hours", 0) or 0)
        max_hours = int(getattr(fobj, "max_workload_hours", 0) or 0)
        if assigned <= 0:
            status = "Unassigned"
            counts["unassigned"] += 1
        elif max_hours > 0 and assigned > max_hours:
            status = "Overloaded"
            counts["overloaded"] += 1
        elif max_hours > 0 and assigned == max_hours:
            status = "Balanced"
            counts["balanced"] += 1
        else:
            status = "Underloaded"
            counts["underloaded"] += 1

        utilization_pct = round((assigned * 100.0 / max_hours), 1) if max_hours > 0 else None
        faculty_workloads.append(
            {
                "id": fobj.id,
                "name": fobj.name,
                "department": fobj.department,
                "email": fobj.email,
                "assigned_hours": assigned,
                "max_hours": max_hours,
                "utilization_pct": utilization_pct,
                "status": status,
            }
        )

    return render(
        request,
        "attendance/faculty_dashboard.html",
        {
            "faculty": faculty,
            "courses": courses,
            "recent_sessions": recent_sessions,
            "now_dt": now_dt,
            "today": today,
            "stats": {
                "sessions_week": sessions_week,
                "sessions_total": sessions_total,
                "students_handled": students_handled,
                "avg_attendance_pct": avg_attendance_pct,
            },
            "alerts": alerts,
            "faculty_workloads": faculty_workloads,
            "faculty_workload_counts": counts,
        },
    )


@login_required
@require_teacher
def faculty_course_students(request: HttpRequest, course_id: int) -> HttpResponse:
    course = get_object_or_404(Course, id=course_id)
    students = (
        Student.objects.filter(course_enrollments__course=course)
        .order_by("roll_no")
        .distinct()
    )
    return render(
        request,
        "attendance/faculty_course_students.html",
        {"course": course, "students": students},
    )


@login_required
@require_teacher
def faculty_course_sessions(request: HttpRequest, course_id: int) -> HttpResponse:
    course = get_object_or_404(Course, id=course_id)
    sessions = (
        AttendanceSession.objects.filter(course=course)
        .annotate(
            present_count=Count(
                "attendancerecord",
                filter=Q(attendancerecord__status=AttendanceRecord.STATUS_PRESENT),
            ),
            absent_count=Count(
                "attendancerecord",
                filter=Q(attendancerecord__status=AttendanceRecord.STATUS_ABSENT),
            ),
            total_count=Count("attendancerecord"),
            enrolled_count=Count("course__enrollments", distinct=True),
        )
        .annotate(
            is_completed=Case(
                When(
                    enrolled_count__gt=0,
                    total_count__gte=F("enrolled_count"),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
        .order_by("-created_at")[:50]
    )
    return render(
        request,
        "attendance/faculty_course_sessions.html",
        {"course": course, "sessions": sessions},
    )


@login_required
@require_teacher
@transaction.atomic
def take_attendance(request: HttpRequest, course_id: int) -> HttpResponse:
    course = get_object_or_404(Course, id=course_id)

    students = (
        Student.objects.filter(course_enrollments__course=course)
        .order_by("roll_no")
        .distinct()
    )

    if request.method == "POST":
        now = timezone.localtime(timezone.now()).replace(second=0, microsecond=0)
        present_ids = {int(x) for x in request.POST.getlist("present") if x.isdigit()}
        session_label = (request.POST.get("session_label", "") or "").strip()

        session = AttendanceSession.objects.create(
            course=course,
            session_start_at=now,
            session_date=now.date(),
            time_slot=now.strftime("%H:%M"),
            session_label=session_label,
        )

        created = 0
        for s in students:
            status = (
                AttendanceRecord.STATUS_PRESENT
                if s.id in present_ids
                else AttendanceRecord.STATUS_ABSENT
            )
            AttendanceRecord.objects.create(
                session=session,
                student=s,
                status=status,
                source="manual",
            )
            created += 1

        messages.success(request, f"Attendance saved for {created} student(s).")
        return redirect("attendance_confirmation", session_id=session.id)

    return render(
        request,
        "attendance/take_attendance.html",
        {
            "course": course,
            "students": students,
        },
    )


@login_required
@require_teacher
def attendance_confirmation(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    total = AttendanceRecord.objects.filter(session=session).count()
    present = AttendanceRecord.objects.filter(
        session=session, status=AttendanceRecord.STATUS_PRESENT
    ).count()
    absent = total - present
    return render(
        request,
        "attendance/attendance_confirmation.html",
        {
            "session": session,
            "total": total,
            "present": present,
            "absent": absent,
        },
    )


@login_required
@require_teacher
def manage_dashboard(request: HttpRequest) -> HttpResponse:
    stats = {
        "students": Student.objects.count(),
        "faculty": Faculty.objects.count(),
        "courses": Course.objects.count(),
        "enrollments": Enrollment.objects.count(),
        "blocks": Block.objects.count(),
        "classrooms": Classroom.objects.count(),
        "face_samples": FaceSample.objects.count(),
        "notifications": Notification.objects.count(),
        "sessions": AttendanceSession.objects.count(),
        "records": AttendanceRecord.objects.count(),
        "vendors": User.objects.filter(groups__name="VENDOR").distinct().count(),
        "food_stalls": FoodStall.objects.count(),
        "menu_categories": MenuCategory.objects.count(),
        "menu_items": MenuItem.objects.count(),
    }

    return render(
        request,
        "attendance/manage/dashboard.html",
        {
            "stats": stats,
        },
    )


@login_required
@require_teacher
def manage_vendors(request: HttpRequest) -> HttpResponse:
    vendors = (
        User.objects.filter(groups__name="VENDOR")
        .order_by("username")
        .distinct()
    )
    return render(request, "attendance/manage/vendors.html", {"vendors": vendors})


@login_required
@require_teacher
def manage_vendor_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = VendorCreateForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            email = (form.cleaned_data.get("email") or "").strip().lower()
            password = form.cleaned_data["password1"]
            stalls = list(form.cleaned_data.get("stalls") or [])

            user = User.objects.create_user(username=username, email=email, password=password)
            group, _ = Group.objects.get_or_create(name="VENDOR")
            user.groups.add(group)

            for s in stalls:
                try:
                    s.operators.add(user)
                except Exception:
                    continue

            messages.success(request, "Vendor created.")
            return redirect("manage_vendors")
    else:
        form = VendorCreateForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Vendor"})


@login_required
@require_teacher
def manage_vendor_delete(request: HttpRequest, user_id: int) -> HttpResponse:
    u = get_object_or_404(User, id=user_id)
    if request.method == "POST":
        u.delete()
        messages.success(request, "Vendor deleted.")
        return redirect("manage_vendors")
    return render(
        request,
        "attendance/manage/confirm_delete.html",
        {"object": u, "type": "Vendor", "cancel_url": "manage_vendors"},
    )


@login_required
@require_teacher
def manage_food_stalls(request: HttpRequest) -> HttpResponse:
    stalls = FoodStall.objects.prefetch_related("operators").order_by("name")
    return render(request, "attendance/manage/food_stalls.html", {"stalls": stalls})


@login_required
@require_teacher
def manage_food_stall_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = FoodStallManageForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Food stall created.")
            return redirect("manage_food_stalls")
    else:
        form = FoodStallManageForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Food Stall"})


@login_required
@require_teacher
def manage_food_stall_edit(request: HttpRequest, stall_id: int) -> HttpResponse:
    stall = get_object_or_404(FoodStall, id=stall_id)
    if request.method == "POST":
        form = FoodStallManageForm(request.POST, instance=stall)
        if form.is_valid():
            form.save()
            messages.success(request, "Food stall updated.")
            return redirect("manage_food_stalls")
    else:
        form = FoodStallManageForm(instance=stall)
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Edit Food Stall"})


@login_required
@require_teacher
def manage_food_stall_delete(request: HttpRequest, stall_id: int) -> HttpResponse:
    stall = get_object_or_404(FoodStall, id=stall_id)
    if request.method == "POST":
        stall.delete()
        messages.success(request, "Food stall deleted.")
        return redirect("manage_food_stalls")
    return render(
        request,
        "attendance/manage/confirm_delete.html",
        {"object": stall, "type": "Food Stall", "cancel_url": "manage_food_stalls"},
    )


@login_required
@require_teacher
def manage_menu_categories(request: HttpRequest) -> HttpResponse:
    categories = MenuCategory.objects.select_related("stall").prefetch_related("operators").order_by(
        "stall__name", "sort_order", "name"
    )
    return render(request, "attendance/manage/menu_categories.html", {"categories": categories})


@login_required
@require_teacher
def manage_menu_category_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = MenuCategoryManageForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Menu category created.")
            return redirect("manage_menu_categories")
    else:
        form = MenuCategoryManageForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Menu Category"})


@login_required
@require_teacher
def manage_menu_category_edit(request: HttpRequest, category_id: int) -> HttpResponse:
    cat = get_object_or_404(MenuCategory, id=category_id)
    if request.method == "POST":
        form = MenuCategoryManageForm(request.POST, instance=cat)
        if form.is_valid():
            form.save()
            messages.success(request, "Menu category updated.")
            return redirect("manage_menu_categories")
    else:
        form = MenuCategoryManageForm(instance=cat)
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Edit Menu Category"})


@login_required
@require_teacher
def manage_menu_category_delete(request: HttpRequest, category_id: int) -> HttpResponse:
    cat = get_object_or_404(MenuCategory, id=category_id)
    if request.method == "POST":
        cat.delete()
        messages.success(request, "Menu category deleted.")
        return redirect("manage_menu_categories")
    return render(
        request,
        "attendance/manage/confirm_delete.html",
        {"object": cat, "type": "Menu Category", "cancel_url": "manage_menu_categories"},
    )


@login_required
@require_teacher
def manage_menu_items(request: HttpRequest) -> HttpResponse:
    items = MenuItem.objects.select_related("stall", "category").order_by("stall__name", "name")
    return render(request, "attendance/manage/menu_items.html", {"items": items})


@login_required
@require_teacher
def manage_menu_item_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = MenuItemManageForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Menu item created.")
            return redirect("manage_menu_items")
    else:
        form = MenuItemManageForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Menu Item"})


@login_required
@require_teacher
def manage_menu_item_edit(request: HttpRequest, item_id: int) -> HttpResponse:
    it = get_object_or_404(MenuItem, id=item_id)
    if request.method == "POST":
        form = MenuItemManageForm(request.POST, instance=it)
        if form.is_valid():
            form.save()
            messages.success(request, "Menu item updated.")
            return redirect("manage_menu_items")
    else:
        form = MenuItemManageForm(instance=it)
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Edit Menu Item"})


@login_required
@require_teacher
def manage_menu_item_delete(request: HttpRequest, item_id: int) -> HttpResponse:
    it = get_object_or_404(MenuItem, id=item_id)
    if request.method == "POST":
        it.delete()
        messages.success(request, "Menu item deleted.")
        return redirect("manage_menu_items")
    return render(
        request,
        "attendance/manage/confirm_delete.html",
        {"object": it, "type": "Menu Item", "cancel_url": "manage_menu_items"},
    )


@login_required
@require_teacher
def manage_blocks(request: HttpRequest) -> HttpResponse:
    blocks = Block.objects.order_by("name")
    return render(request, "attendance/manage/blocks.html", {"blocks": blocks})


@login_required
@require_teacher
def manage_block_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = BlockForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Block created.")
            return redirect("manage_blocks")
    else:
        form = BlockForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Block"})


@login_required
@require_teacher
def manage_block_edit(request: HttpRequest, block_id: int) -> HttpResponse:
    b = get_object_or_404(Block, id=block_id)
    if request.method == "POST":
        form = BlockForm(request.POST, instance=b)
        if form.is_valid():
            form.save()
            messages.success(request, "Block updated.")
            return redirect("manage_blocks")
    else:
        form = BlockForm(instance=b)
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Edit Block"})


@login_required
@require_teacher
def manage_block_delete(request: HttpRequest, block_id: int) -> HttpResponse:
    b = get_object_or_404(Block, id=block_id)
    if Classroom.objects.filter(block=b).exists():
        messages.error(request, "Cannot delete block while classrooms exist in it. Delete/move classrooms first.")
        return redirect("manage_blocks")
    if request.method == "POST":
        b.delete()
        messages.success(request, "Block deleted.")
        return redirect("manage_blocks")
    return render(
        request,
        "attendance/manage/confirm_delete.html",
        {"object": b, "type": "Block", "cancel_url": "manage_blocks"},
    )


@login_required
@require_teacher
def manage_faculty(request: HttpRequest) -> HttpResponse:
    faculty = Faculty.objects.order_by("name")
    return render(request, "attendance/manage/faculty.html", {"faculty": faculty})


@login_required
@require_teacher
def manage_faculty_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = FacultyForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Faculty created.")
            return redirect("manage_faculty")
    else:
        form = FacultyForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Faculty"})


@login_required
@require_teacher
def manage_faculty_edit(request: HttpRequest, faculty_id: int) -> HttpResponse:
    f = get_object_or_404(Faculty, id=faculty_id)
    if request.method == "POST":
        form = FacultyForm(request.POST, instance=f)
        if form.is_valid():
            form.save()
            messages.success(request, "Faculty updated.")
            return redirect("manage_faculty")
    else:
        form = FacultyForm(instance=f)
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Edit Faculty"})


@login_required
@require_teacher
def manage_faculty_delete(request: HttpRequest, faculty_id: int) -> HttpResponse:
    f = get_object_or_404(Faculty, id=faculty_id)
    if Course.objects.filter(faculty=f).exists():
        messages.error(request, "Cannot delete faculty while courses are assigned. Reassign or remove faculty from courses first.")
        return redirect("manage_faculty")
    if request.method == "POST":
        f.delete()
        messages.success(request, "Faculty deleted.")
        return redirect("manage_faculty")
    return render(request, "attendance/manage/confirm_delete.html", {"object": f, "type": "Faculty", "cancel_url": "manage_faculty"})


@login_required
@require_teacher
def manage_classrooms(request: HttpRequest) -> HttpResponse:
    classrooms = Classroom.objects.select_related("block").order_by("block__name", "room_number")
    return render(request, "attendance/manage/classrooms.html", {"classrooms": classrooms})


@login_required
@require_teacher
def manage_classroom_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ClassroomForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Classroom created.")
            return redirect("manage_classrooms")
    else:
        form = ClassroomForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Classroom"})


@login_required
@require_teacher
def manage_classroom_edit(request: HttpRequest, classroom_id: int) -> HttpResponse:
    c = get_object_or_404(Classroom, id=classroom_id)
    if request.method == "POST":
        form = ClassroomForm(request.POST, instance=c)
        if form.is_valid():
            form.save()
            messages.success(request, "Classroom updated.")
            return redirect("manage_classrooms")
    else:
        form = ClassroomForm(instance=c)
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Edit Classroom"})


@login_required
@require_teacher
def manage_classroom_delete(request: HttpRequest, classroom_id: int) -> HttpResponse:
    c = get_object_or_404(Classroom, id=classroom_id)
    if request.method == "POST":
        c.delete()
        messages.success(request, "Classroom deleted.")
        return redirect("manage_classrooms")
    return render(request, "attendance/manage/confirm_delete.html", {"object": c, "type": "Classroom", "cancel_url": "manage_classrooms"})


@login_required
@require_teacher
def manage_students(request: HttpRequest) -> HttpResponse:
    students = Student.objects.order_by("roll_no")
    return render(request, "attendance/manage/students.html", {"students": students})


@login_required
@require_teacher
def manage_student_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = StudentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Student created.")
            return redirect("manage_students")
    else:
        form = StudentForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Student"})


@login_required
@require_teacher
def manage_student_edit(request: HttpRequest, student_id: int) -> HttpResponse:
    student = get_object_or_404(Student, id=student_id)
    if request.method == "POST":
        form = StudentForm(request.POST, instance=student)
        if form.is_valid():
            form.save()
            messages.success(request, "Student updated.")
            return redirect("manage_students")
    else:
        form = StudentForm(instance=student)
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Edit Student"})


@login_required
@require_teacher
def manage_student_delete(request: HttpRequest, student_id: int) -> HttpResponse:
    student = get_object_or_404(Student, id=student_id)
    if request.method == "POST":
        student.delete()
        messages.success(request, "Student deleted.")
        return redirect("manage_students")
    return render(request, "attendance/manage/confirm_delete.html", {"object": student, "type": "Student"})


@login_required
@require_teacher
def manage_courses(request: HttpRequest) -> HttpResponse:
    courses = Course.objects.order_by("code")
    return render(request, "attendance/manage/courses.html", {"courses": courses})


@login_required
@require_teacher
def manage_course_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = CourseCreateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Course created.")
            return redirect("manage_courses")
    else:
        form = CourseCreateForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Course"})


@login_required
@require_teacher
def manage_course_edit(request: HttpRequest, course_id: int) -> HttpResponse:
    course = get_object_or_404(Course, id=course_id)
    if request.method == "POST":
        form = CourseCreateForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, "Course updated.")
            return redirect("manage_courses")
    else:
        form = CourseCreateForm(instance=course)
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Edit Course"})


@login_required
@require_teacher
def manage_course_delete(request: HttpRequest, course_id: int) -> HttpResponse:
    course = get_object_or_404(Course, id=course_id)
    if request.method == "POST":
        course.delete()
        messages.success(request, "Course deleted.")
        return redirect("manage_courses")
    return render(request, "attendance/manage/confirm_delete.html", {"object": course, "type": "Course"})


@login_required
@require_teacher
def manage_enrollments(request: HttpRequest) -> HttpResponse:
    enrollments = Enrollment.objects.select_related("student", "course").order_by("course__code", "student__roll_no")
    return render(request, "attendance/manage/enrollments.html", {"enrollments": enrollments})


@login_required
@require_teacher
def manage_enrollment_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = EnrollmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Enrollment created.")
            return redirect("manage_enrollments")
    else:
        form = EnrollmentForm()
    return render(request, "attendance/manage/form.html", {"form": form, "title": "Add Enrollment"})


@login_required
@require_teacher
def manage_face_samples(request: HttpRequest) -> HttpResponse:
    samples = FaceSample.objects.select_related("student").order_by("-created_at")
    return render(request, "attendance/manage/face_samples.html", {"samples": samples})


@login_required
@require_teacher
def manage_face_sample_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = FaceSampleMultiForm(request.POST, request.FILES)
        if form.is_valid():
            student = form.cleaned_data["student"]
            images = form.cleaned_data["images"]
            for img in images:
                FaceSample.objects.create(student=student, image=img)
            messages.success(request, "Face data uploaded.")
            return redirect("manage_face_samples")
    else:
        form = FaceSampleMultiForm()
    return render(request, "attendance/manage/face_data_upload.html", {"form": form})


@login_required
def manage_face_sample_delete(request: HttpRequest, face_sample_id: int) -> HttpResponse:
    fs = get_object_or_404(FaceSample.objects.select_related("student"), id=face_sample_id)
    if request.method == "POST":
        if fs.image:
            fs.image.delete(save=False)
        fs.delete()
        messages.success(request, "Face data deleted.")
        return redirect("manage_face_samples")

    return render(request, "attendance/manage/confirm_delete.html", {"object": fs, "type": "Face Data"})


@login_required
@require_teacher
@transaction.atomic
def manage_face_samples_delete_all(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        samples = list(FaceSample.objects.all())
        deleted = 0
        for fs in samples:
            try:
                if fs.image:
                    fs.image.delete(save=False)
            except Exception:
                pass
            fs.delete()
            deleted += 1

        messages.success(request, f"Deleted {deleted} face data item(s).")
        return redirect("manage_face_samples")

    return render(
        request,
        "attendance/manage/confirm_delete.html",
        {"object": None, "type": "All Face Data", "cancel_url": "manage_face_samples"},
    )


@login_required
@require_teacher
def manage_notifications(request: HttpRequest) -> HttpResponse:
    notifications = Notification.objects.select_related("recipient_student").order_by("-created_at")[:200]
    return render(request, "attendance/manage/notifications.html", {"notifications": notifications})


@login_required
@require_teacher
def manage_sessions(request: HttpRequest) -> HttpResponse:
    sessions = (
        AttendanceSession.objects.select_related("course")
        .annotate(
            enrolled_count=Count("course__enrollments", distinct=True),
            records_count=Count("attendancerecord", distinct=True),
        )
        .annotate(
            is_completed=Case(
                When(
                    enrolled_count__gt=0,
                    records_count__gte=F("enrolled_count"),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
        .order_by("-created_at")[:200]
    )
    return render(request, "attendance/manage/sessions.html", {"sessions": sessions})


@login_required
@require_teacher
def manage_records(request: HttpRequest) -> HttpResponse:
    session_id = request.GET.get("session")
    qs = AttendanceRecord.objects.select_related("session", "session__course", "student").order_by(
        "-updated_at"
    )

    selected_session = None
    if session_id and session_id.isdigit():
        selected_session = AttendanceSession.objects.select_related("course").filter(id=int(session_id)).first()
        if selected_session:
            qs = qs.filter(session=selected_session)

    sessions = AttendanceSession.objects.select_related("course").order_by("-created_at")[:200]
    records = qs[:500]
    return render(
        request,
        "attendance/manage/records.html",
        {"records": records, "sessions": sessions, "selected_session": selected_session},
    )


@login_required
def create_session(request: HttpRequest) -> HttpResponse:
    user = getattr(request, "user", None)
    email = (getattr(user, "email", "") or "").strip().lower()
    faculty = Faculty.objects.filter(email__iexact=email).first() if email else None
    allowed_courses = Course.objects.order_by("code")
    if faculty is not None:
        allowed_courses = allowed_courses.filter(faculty=faculty)

    if request.method == "POST":
        form = AttendanceSessionCreateForm(request.POST)
        if "course" in form.fields:
            form.fields["course"].queryset = allowed_courses
        if form.is_valid():
            session = form.save()
            messages.success(request, "Session created. Now choose how to mark attendance.")
            return redirect("mark_attendance_choice", session_id=session.id)
    else:
        now = timezone.localtime(timezone.now()).replace(second=0, microsecond=0) + timezone.timedelta(minutes=1)
        initial: dict[str, object] = {"session_start_at": now}
        course_id = request.GET.get("course")
        if course_id and course_id.isdigit():
            initial["course"] = int(course_id)
        form = AttendanceSessionCreateForm(initial=initial)
        if "course" in form.fields:
            form.fields["course"].queryset = allowed_courses

    return render(request, "attendance/create_session.html", {"form": form})


@login_required
@require_teacher
def create_makeup_session(request: HttpRequest) -> HttpResponse:
    user = getattr(request, "user", None)
    email = (getattr(user, "email", "") or "").strip().lower()
    faculty = Faculty.objects.filter(email__iexact=email).first() if email else None
    allowed_courses = Course.objects.order_by("code")
    if faculty is not None:
        allowed_courses = allowed_courses.filter(faculty=faculty)

    if request.method == "POST":
        form = MakeupSessionCreateForm(request.POST)
        if "course" in form.fields:
            form.fields["course"].queryset = allowed_courses
        if form.is_valid():
            session = form.save(commit=False)
            session.session_type = AttendanceSession.TYPE_MAKEUP
            session.remedial_code = _unique_remedial_code()
            session.remedial_expires_at = session.session_end_at
            session.save()

            if bool(form.cleaned_data.get("notify_students")):
                enrolled_students = list(
                    Student.objects.filter(course_enrollments__course=session.course)
                    .order_by("id")
                    .distinct()
                )
                expiry_str = (
                    timezone.localtime(session.remedial_expires_at).strftime("%Y-%m-%d %H:%M")
                    if session.remedial_expires_at
                    else "-"
                )
                msg = (
                    f"Make-Up Class: {session.course.code} ({session.course.name}). "
                    f"Remedial Code: {session.remedial_code}. Expires: {expiry_str}. "
                    "Login → Remedial Code to mark attendance."
                )
                Notification.objects.bulk_create(
                    [
                        Notification(recipient_student=s, channel="simulated", message=msg)
                        for s in enrolled_students
                    ],
                    ignore_conflicts=False,
                )
            messages.success(request, "Make-up session created. Share the remedial code with students.")
            return redirect("makeup_session_code", session_id=session.id)
    else:
        now = timezone.localtime(timezone.now()).replace(second=0, microsecond=0) + timezone.timedelta(minutes=1)
        initial: dict[str, object] = {"session_date": now.date(), "start_time": now.time()}
        course_id = request.GET.get("course")
        if course_id and course_id.isdigit():
            initial["course"] = int(course_id)
        form = MakeupSessionCreateForm(initial=initial)
        if "course" in form.fields:
            form.fields["course"].queryset = allowed_courses

    return render(request, "attendance/create_makeup_session.html", {"form": form})


@login_required
@require_teacher
def classroom_busy_check(request: HttpRequest) -> JsonResponse:
    classroom_id = request.GET.get("classroom")
    date = request.GET.get("date")
    start_time = request.GET.get("start")
    end_time = request.GET.get("end")

    if not (classroom_id and classroom_id.isdigit() and date and start_time and end_time):
        return JsonResponse({"ok": False, "busy": False, "message": ""})

    classroom = Classroom.objects.select_related("block").filter(pk=int(classroom_id)).first()
    if classroom is None:
        return JsonResponse({"ok": False, "busy": False, "message": ""})

    try:
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.fromisoformat(f"{date}T{start_time}"), tz)
        end_dt = timezone.make_aware(datetime.fromisoformat(f"{date}T{end_time}"), tz)
    except Exception:
        return JsonResponse({"ok": False, "busy": False, "message": ""})

    if end_dt <= start_dt:
        return JsonResponse({"ok": True, "busy": True, "message": "End time must be after start time."})

    overlaps = AttendanceSession.objects.filter(
        classroom=classroom,
        session_start_at__lt=end_dt,
    ).filter(
        Q(session_end_at__gt=start_dt) | Q(session_end_at__isnull=True, session_start_at__gt=start_dt)
    )

    if overlaps.exists():
        return JsonResponse(
            {
                "ok": True,
                "busy": True,
                "message": "Busy (already booked by some other faculty).",
            }
        )
    return JsonResponse({"ok": True, "busy": False, "message": "Available"})


@login_required
@require_teacher
def available_classrooms(request: HttpRequest) -> JsonResponse:
    date = request.GET.get("date")
    start_time = request.GET.get("start")
    end_time = request.GET.get("end")

    if not (date and start_time and end_time):
        return JsonResponse({"ok": False, "items": []})

    try:
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime.fromisoformat(f"{date}T{start_time}"), tz)
        end_dt = timezone.make_aware(datetime.fromisoformat(f"{date}T{end_time}"), tz)
    except Exception:
        return JsonResponse({"ok": False, "items": []})

    if end_dt <= start_dt:
        return JsonResponse({"ok": True, "items": []})

    overlaps = (
        AttendanceSession.objects.filter(
            classroom__isnull=False,
            session_start_at__lt=end_dt,
        )
        .filter(Q(session_end_at__gt=start_dt) | Q(session_end_at__isnull=True))
        .values_list("classroom_id", flat=True)
        .distinct()
    )
    busy_ids = list(overlaps)

    qs = Classroom.objects.select_related("block").order_by("block__name", "room_number")
    if busy_ids:
        qs = qs.exclude(id__in=busy_ids)

    items = [
        {
            "id": int(c.id),
            "label": f"{getattr(getattr(c, 'block', None), 'name', '')} - {getattr(c, 'room_number', '')}".strip(
                " -"
            ),
        }
        for c in qs[:12]
    ]
    return JsonResponse({"ok": True, "items": items})


@login_required
@require_teacher
def makeup_session_code(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    return render(request, "attendance/makeup_session_code.html", {"session": session})


@login_required
@require_student
@transaction.atomic
def remedial_code_entry(request: HttpRequest) -> HttpResponse:
    student = Student.objects.filter(user=request.user).first()
    if student is None:
        messages.error(request, "Student profile not linked. Contact admin.")
        return redirect("home")

    if request.method == "POST":
        form = RemedialCodeEntryForm(request.POST)
        if form.is_valid():
            code = (form.cleaned_data.get("code") or "").strip().upper()
            session = (
                AttendanceSession.objects.select_related("course")
                .filter(session_type=AttendanceSession.TYPE_MAKEUP, remedial_code=code)
                .first()
            )
            if session is None:
                messages.error(request, "Invalid remedial code.")
                return render(request, "attendance/remedial_code_entry.html", {"form": form})

            now = timezone.now()
            start_at = getattr(session, "session_start_at", None)
            end_at = getattr(session, "session_end_at", None)
            expires_at = getattr(session, "remedial_expires_at", None)

            if start_at is None or end_at is None:
                messages.error(
                    request,
                    "This make-up session is not configured with a valid class time window. Contact faculty.",
                )
                return render(request, "attendance/remedial_code_entry.html", {"form": form})

            if start_at and now < start_at:
                messages.error(request, "This make-up session is not active yet. Try again during class time.")
                return render(request, "attendance/remedial_code_entry.html", {"form": form})

            cutoff = min(end_at, expires_at) if expires_at else end_at

            if now > cutoff:
                messages.error(request, "This make-up session has ended. Remedial code is expired.")
                return render(request, "attendance/remedial_code_entry.html", {"form": form})

            if not Enrollment.objects.filter(student=student, course=session.course).exists():
                messages.error(request, "You are not enrolled in this course.")
                return render(request, "attendance/remedial_code_entry.html", {"form": form})

            existing = AttendanceRecord.objects.filter(session=session, student=student).first()
            if existing is not None:
                messages.success(request, "Attendance already marked for this make-up session.")
                return render(
                    request,
                    "attendance/remedial_code_entry.html",
                    {"form": RemedialCodeEntryForm(), "last_session": session},
                )

            AttendanceRecord.objects.create(
                session=session,
                student=student,
                status=AttendanceRecord.STATUS_PRESENT,
                source="remedial_code",
            )
            messages.success(request, f"Attendance marked for {session.course.code}.")
            return render(
                request,
                "attendance/remedial_code_entry.html",
                {"form": RemedialCodeEntryForm(), "last_session": session},
            )
    else:
        form = RemedialCodeEntryForm()

    return render(request, "attendance/remedial_code_entry.html", {"form": form})


@login_required
def mark_attendance_choice(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course", "subject", "classroom"), id=session_id)
    students = (
        Student.objects.filter(course_enrollments__course=session.course)
        .order_by("roll_no")
        .distinct()
    )
    
    return render(request, "attendance/mark_attendance_choice.html", {
        "session": session,
        "student_count": students.count(),
        "is_completed": _session_is_completed(session=session),
    })


@login_required
def session_manual(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(
        AttendanceSession.objects.select_related("course"),
        id=session_id,
    )
    students = (
        Student.objects.filter(course_enrollments__course=session.course)
        .order_by("roll_no")
        .distinct()
    )

    existing = {
        r.student_id: r
        for r in AttendanceRecord.objects.filter(session=session).select_related("student")
    }
    student_rows = []
    for s in students:
        rec = existing.get(s.id)
        student_rows.append(
            {
                "student": s,
                "status": rec.status if rec else "",
                "source": rec.source if rec else "",
            }
        )

    return render(
        request,
        "attendance/session_manual.html",
        {
            "session": session,
            "student_rows": student_rows,
            "counts": _session_counts(session=session),
        },
    )


@login_required
def session_face(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(
        AttendanceSession.objects.select_related("course"),
        id=session_id,
    )
    return render(
        request,
        "attendance/session_face.html",
        {
            "session": session,
            "photo_form": AttendancePhotoUploadForm(),
            "counts": _session_counts(session=session),
        },
    )


@login_required
def session_mark_summary(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(
        AttendanceSession.objects.select_related("course", "subject", "classroom", "classroom__block"),
        id=session_id,
    )
    counts = _session_counts(session=session)
    return render(
        request,
        "attendance/session_mark_summary.html",
        {
            "session": session,
            "counts": counts,
            "is_completed": bool(counts["total"] > 0 and counts["marked"] >= counts["total"]),
        },
    )


@login_required
def edit_session(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    if session.session_type == AttendanceSession.TYPE_MAKEUP and timezone.now() >= session.session_start_at:
        messages.error(request, "This make-up session is locked and cannot be edited.")
        return redirect("session_history", session_id=session.id)
    if request.method == "POST":
        form = AttendanceSessionCreateForm(request.POST, instance=session)
        if form.is_valid():
            form.save()
            messages.success(request, "Session updated.")
            return redirect("session_face", session_id=session.id)
    else:
        form = AttendanceSessionCreateForm(instance=session)

    return render(request, "attendance/edit_session.html", {"form": form, "session": session})


@login_required
def delete_session(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    if request.method == "POST":
        session.delete()
        messages.success(request, "Session deleted.")
        return redirect("attendance_home")

    return render(request, "attendance/session_confirm_delete.html", {"session": session})


@login_required
def session_history(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(
        AttendanceSession.objects.select_related(
            "course",
            "course__faculty",
            "subject",
            "classroom",
            "classroom__block",
        ),
        id=session_id,
    )
    students = list(
        Student.objects.filter(course_enrollments__course=session.course)
        .order_by("roll_no")
        .distinct()
    )

    records = {
        r.student_id: r
        for r in AttendanceRecord.objects.filter(session=session).select_related("student")
    }

    present_rows: list[dict[str, object]] = []
    absent_rows: list[dict[str, object]] = []
    unmarked_rows: list[dict[str, object]] = []

    for s in students:
        rec = records.get(s.id)
        if rec is None:
            unmarked_rows.append({"student": s, "status": "", "source": ""})
        elif rec.status == AttendanceRecord.STATUS_PRESENT:
            present_rows.append({"student": s, "status": rec.status, "source": rec.source})
        else:
            absent_rows.append({"student": s, "status": rec.status, "source": rec.source})

    participation_pct = None
    low_participation = False
    if session.session_type == AttendanceSession.TYPE_MAKEUP:
        total = len(students)
        present = len(present_rows)
        participation_pct = round((present * 100.0 / total), 1) if total > 0 else 0.0
        low_participation = bool(total > 0 and participation_pct < 60.0)

    return render(
        request,
        "attendance/session_history.html",
        {
            "session": session,
            "present_rows": present_rows,
            "absent_rows": absent_rows,
            "unmarked_rows": unmarked_rows,
            "is_completed": bool(len(students) > 0 and (len(present_rows) + len(absent_rows)) >= len(students)),
            "participation_pct": participation_pct,
            "low_participation": low_participation,
            "counts": {
                "total": len(students),
                "present": len(present_rows),
                "absent": len(absent_rows),
                "unmarked": len(unmarked_rows),
            },
        },
    )


@login_required
def session_detail(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    if _session_is_completed(session=session):
        return redirect("session_history", session_id=session.id)
    return redirect("mark_attendance_choice", session_id=session.id)


@login_required
@transaction.atomic
def mark_attendance_by_photo(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    students = (
        Student.objects.filter(course_enrollments__course=session.course)
        .order_by("roll_no")
        .distinct()
    )

    if request.method != "POST":
        return redirect("session_face", session_id=session.id)

    form = AttendancePhotoUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Please upload a valid image.")
        return redirect("session_face", session_id=session.id)

    # Build training set from stored FaceSample images
    images_by_label: dict[int, list[np.ndarray]] = {}
    usable_counts: dict[int, int] = {}
    for fs in (
        FaceSample.objects.select_related("student")
        .filter(student__course_enrollments__course=session.course)
        .distinct()
    ):
        try:
            img = cv2.imread(fs.image.path)
        except Exception:
            img = None
        if img is None:
            continue
        images_by_label.setdefault(fs.student_id, []).append(img)
        if detect_faces_count(img) > 0:
            usable_counts[fs.student_id] = usable_counts.get(fs.student_id, 0) + 1

    # Require more samples to reduce mis-labeling (important when two students look similar).
    min_samples_per_student = 5
    sample_counts = {sid: len(imgs) for (sid, imgs) in images_by_label.items()}

    # Filter out images where no face is detectable (training would be empty otherwise)
    filtered: dict[int, list[np.ndarray]] = {}
    for sid, imgs in images_by_label.items():
        keep = [im for im in imgs if detect_faces_count(im) > 0]
        if len(keep) >= min_samples_per_student:
            filtered[sid] = keep
    images_by_label = filtered

    try:
        train_images, train_labels = build_training_set(images_by_label)
        recognizer = train_lbph(train_images, train_labels)
    except Exception:
        enrolled_ids = [s.id for s in students]
        parts = []
        for sid in enrolled_ids:
            parts.append(f"{sample_counts.get(sid, 0)}/{usable_counts.get(sid, 0)}")
        counts_str = ", ".join(parts)
        messages.error(
            request,
            "Face training data is missing/invalid. Upload Face Data in Manage Data (need at least 5 clear photos with a detectable face per enrolled student). "
            f"Samples found (total/usable) in course order: [{counts_str}]",
        )
        return redirect("session_face", session_id=session.id)

    # Decode uploaded image
    upload = form.cleaned_data["photo"]
    pil = Image.open(upload).convert("RGB")
    rgb = np.array(pil)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    recognized = recognize_faces_in_image(recognizer, bgr)

    if not recognized:
        messages.error(
            request,
            "No face detected in the uploaded image. Please try again with a clearer photo (front face, good lighting).",
        )
        return redirect("session_face", session_id=session.id)

    # LBPH: lower confidence is better.
    # Use a tighter threshold to reduce false positives.
    threshold = 60.0
    allowed_ids = {s.id for s in students}

    # Choose best (lowest) confidence per predicted label
    best_by_id: dict[int, float] = {}
    for r in recognized:
        if r.label not in allowed_ids:
            continue
        conf = float(r.confidence)
        prev = best_by_id.get(r.label)
        if prev is None or conf < prev:
            best_by_id[r.label] = conf

    sorted_matches = sorted(best_by_id.items(), key=lambda x: x[1])

    # Ambiguity guard:
    # Only apply when the upload appears to contain a single face.
    # For group photos, multiple different students can (correctly) have close confidence.
    if len(recognized) <= 1 and len(sorted_matches) >= 2:
        best_conf = float(sorted_matches[0][1])
        second_conf = float(sorted_matches[1][1])
        if (second_conf - best_conf) < 12.0:
            messages.error(
                request,
                "Face match is ambiguous (two students are too close). Please try again with better lighting/angle or improve Face Data.",
            )
            return redirect("session_face", session_id=session.id)

    present_ids = {sid for (sid, conf) in sorted_matches if conf <= threshold}

    if not present_ids:
        messages.error(
            request,
            "No confident face match found. Please add more Face Data (5-10 clear photos per student) and retry with better lighting/angle.",
        )
        return redirect("session_face", session_id=session.id)

    newly_marked = 0
    for s in students:
        status = (
            AttendanceRecord.STATUS_PRESENT
            if s.id in present_ids
            else AttendanceRecord.STATUS_ABSENT
        )
        obj, created = AttendanceRecord.objects.update_or_create(
            session=session,
            student=s,
            defaults={"status": status, "source": "face"},
        )
        if created or obj.status != status:
            newly_marked += 1

    absentees = [s for s in students if s.id not in present_ids]
    email_failures: list[str] = []
    email_sent = 0
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
    email_enabled = bool((from_email or "").strip())
    for s in absentees:
        msg = (
            f"Absent detected: {s.full_name} ({s.roll_no}) was marked ABSENT for "
            f"{session.course.code} on {session.session_date}."
        )
        Notification.objects.create(recipient_student=s, channel="simulated", message=msg)
        if email_enabled:
            ok, reason = _send_absent_email(student=s, session=session)
            if not ok:
                email_failures.append(f"{s.roll_no}: {reason}")
            else:
                email_sent += 1

    msg = f"Photo-based marking complete. Detected present: {len(present_ids)} | Absentees: {len(absentees)}"
    messages.success(request, msg)
    if not email_enabled and absentees:
        messages.warning(
            request,
            "Absent emails were not sent because email is not configured for this server process. "
            "Set SMARTLPU_EMAIL_HOST_USER/SMARTLPU_EMAIL_HOST_PASSWORD/SMARTLPU_DEFAULT_FROM_EMAIL and restart the server.",
        )
    elif absentees:
        messages.info(
            request,
            f"Absent email status: sent {email_sent}/{len(absentees)}. Failed: {len(email_failures)}.",
        )
    if email_failures:
        preview = "; ".join(email_failures[:3])
        extra = "" if len(email_failures) <= 3 else f" (+{len(email_failures) - 3} more)"
        messages.warning(request, f"Absent emails not sent for {len(email_failures)} student(s): {preview}{extra}")

    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if wants_json:
        counts = _session_counts(session=session)
        return JsonResponse(
            {
                "ok": True,
                "newly_marked": int(newly_marked),
                "present_detected": int(len(present_ids)),
                "absentees": int(len(absentees)),
                "counts": counts,
                "message": msg,
            }
        )

    return redirect("session_mark_summary", session_id=session.id)


@login_required
@transaction.atomic
def mark_attendance(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    students = (
        Student.objects.filter(course_enrollments__course=session.course)
        .order_by("roll_no")
        .distinct()
    )

    if request.method != "POST":
        return redirect("session_manual", session_id=session.id)

    action = request.POST.get("action", "")

    if action == "mark_all_present":
        for s in students:
            AttendanceRecord.objects.update_or_create(
                session=session,
                student=s,
                defaults={"status": AttendanceRecord.STATUS_PRESENT, "source": "manual"},
            )
        messages.success(request, "Marked all students present.")
        return redirect("session_mark_summary", session_id=session.id)

    present_ids = {int(x) for x in request.POST.getlist("present") if x.isdigit()}

    # Save records
    for s in students:
        status = (
            AttendanceRecord.STATUS_PRESENT
            if s.id in present_ids
            else AttendanceRecord.STATUS_ABSENT
        )
        AttendanceRecord.objects.update_or_create(
            session=session,
            student=s,
            defaults={"status": status, "source": "manual"},
        )

    # Absentee detection + notifications (simulated)
    absentees = [s for s in students if s.id not in present_ids]
    email_failures: list[str] = []
    email_sent = 0
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
    email_enabled = bool((from_email or "").strip())
    for s in absentees:
        msg = (
            f"Absent detected: {s.full_name} ({s.roll_no}) was marked ABSENT for "
            f"{session.course.code} on {session.session_date}."
        )
        Notification.objects.create(recipient_student=s, channel="simulated", message=msg)
        if email_enabled:
            ok, reason = _send_absent_email(student=s, session=session)
            if not ok:
                email_failures.append(f"{s.roll_no}: {reason}")
            else:
                email_sent += 1

    messages.success(request, f"Attendance saved. Absentees: {len(absentees)}")
    if not email_enabled and absentees:
        messages.warning(
            request,
            "Absent emails were not sent because email is not configured for this server process. "
            "Set SMARTLPU_EMAIL_HOST_USER/SMARTLPU_EMAIL_HOST_PASSWORD/SMARTLPU_DEFAULT_FROM_EMAIL and restart the server.",
        )
    elif absentees:
        messages.info(
            request,
            f"Absent email status: sent {email_sent}/{len(absentees)}. Failed: {len(email_failures)}.",
        )
    if email_failures:
        preview = "; ".join(email_failures[:3])
        extra = "" if len(email_failures) <= 3 else f" (+{len(email_failures) - 3} more)"
        messages.warning(request, f"Absent emails not sent for {len(email_failures)} student(s): {preview}{extra}")
    return redirect("session_mark_summary", session_id=session.id)


@login_required
@transaction.atomic
def live_attendance_frame(request: HttpRequest, session_id: int) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    state = _live_get_state(request, session_id)
    now = time.time()
    last_ts = float(state.get("last_ts", 0.0))
    if now - last_ts < 0.35:
        return JsonResponse({"ok": False, "error": "Too many requests"}, status=429)
    state["last_ts"] = now

    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    students = (
        Student.objects.filter(course_enrollments__course=session.course)
        .order_by("roll_no")
        .distinct()
    )
    allowed_ids = {s.id for s in students}

    try:
        raw = request.body.decode("utf-8")
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid body"}, status=400)

    try:
        import json

        payload = json.loads(raw)
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    img_b64 = payload.get("image", "")
    require_blink = bool(payload.get("require_blink", False))
    if not isinstance(img_b64, str) or not img_b64:
        return JsonResponse({"ok": False, "error": "Missing image"}, status=400)

    if len(img_b64) > 2_500_000:
        return JsonResponse({"ok": False, "error": "Image too large"}, status=413)

    if img_b64.startswith("data:"):
        img_b64 = img_b64.split(",", 1)[-1]

    try:
        img_bytes = base64.b64decode(img_b64)
    except Exception:
        return JsonResponse({"ok": False, "error": "Bad base64"}, status=400)

    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        return JsonResponse({"ok": False, "error": "Could not decode image"}, status=400)

    # Update liveness state
    eyes_count = detect_eyes_count(bgr)
    eyes: deque[int] = state["eyes"]  # type: ignore[assignment]
    eyes.append(int(eyes_count))
    if _blink_seen(state):
        state["last_blink_ts"] = now

    if require_blink:
        last_blink_ts = float(state.get("last_blink_ts", 0.0))
        if now - last_blink_ts > 6.0:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Liveness check failed (blink not detected yet).",
                    "eyes": int(eyes_count),
                    "blink_recent": False,
                },
                status=200,
            )

    # Build training set from stored FaceSample images (only enrolled students)
    images_by_label: dict[int, list[np.ndarray]] = {}
    usable_counts: dict[int, int] = {}
    for fs in (
        FaceSample.objects.select_related("student")
        .filter(student__course_enrollments__course=session.course)
        .distinct()
    ):
        try:
            img = cv2.imread(fs.image.path)
        except Exception:
            img = None
        if img is None:
            continue
        images_by_label.setdefault(fs.student_id, []).append(img)
        if detect_faces_count(img) > 0:
            usable_counts[fs.student_id] = usable_counts.get(fs.student_id, 0) + 1

    # Only train on students with enough samples to reduce mis-labeling.
    min_samples_per_student = 4
    filtered: dict[int, list[np.ndarray]] = {}
    for sid, imgs in images_by_label.items():
        keep = [im for im in imgs if detect_faces_count(im) > 0]
        if len(keep) >= min_samples_per_student:
            filtered[sid] = keep
    images_by_label = filtered

    try:
        train_images, train_labels = build_training_set(images_by_label)
        recognizer = train_lbph(train_images, train_labels)
    except Exception:
        parts = []
        for sid in students.values_list("id", flat=True):
            total = FaceSample.objects.filter(student_id=sid).count()
            parts.append(f"{total}/{usable_counts.get(int(sid), 0)}")
        diag = ", ".join(parts)
        return JsonResponse(
            {
                "ok": False,
                "error": "Face data missing/invalid. Upload Face Data in Manage Data (need >= 4 clear photos with a detectable face per enrolled student).",
                "diag": f"total/usable in session course: [{diag}]",
                "eyes": int(eyes_count),
                "blink_recent": (now - float(state.get("last_blink_ts", 0.0)) <= 6.0),
            },
            status=200,
        )

    recognized = recognize_faces_in_image(recognizer, bgr)

    # Repeated-frame confirmation:
    # - Use strict threshold first (reduces false positives)
    # - If the same ID repeats across frames, allow a slightly looser threshold
    strict_threshold = 95.0
    loose_threshold = 120.0
    confirm_frames = 3
    confirm_window_s = 3.0

    candidates: dict[int, dict[str, float]] = state.get("candidates", {})  # type: ignore[assignment]

    # Decay old candidates
    for sid in list(candidates.keys()):
        last_seen = float(candidates[sid].get("last_seen", 0.0))
        if now - last_seen > confirm_window_s:
            candidates.pop(sid, None)

    # For each recognized face, choose best (lowest) confidence for that label
    best_by_id: dict[int, float] = {}
    for r in recognized:
        if r.label not in allowed_ids:
            continue
        conf = float(r.confidence)
        prev = best_by_id.get(r.label)
        if prev is None or conf < prev:
            best_by_id[r.label] = conf

    detected_ids: set[int] = set()
    pending_ids: set[int] = set()
    sorted_matches = sorted(best_by_id.items(), key=lambda x: x[1])
    top_matches = sorted_matches[:3]

    # Ambiguity guard: if the best match isn't clearly better than the second best,
    # do not mark anyone for this frame.
    if len(sorted_matches) >= 2:
        best_conf = float(sorted_matches[0][1])
        second_conf = float(sorted_matches[1][1])
        if (second_conf - best_conf) < 12.0:
            return JsonResponse(
                {
                    "ok": True,
                    "present_detected": 0,
                    "newly_marked": 0,
                    "pending": 0,
                    "faces_detected": len(recognized),
                    "trained_faces": len(train_images),
                    "trained_students": len(set(train_labels)),
                    "top_matches": [{"id": int(i), "conf": float(c)} for (i, c) in top_matches],
                    "eyes": int(eyes_count),
                    "blink_recent": (now - float(state.get("last_blink_ts", 0.0)) <= 6.0),
                }
            )

    for sid, conf in best_by_id.items():
        info = candidates.get(sid)
        prev_count = int(info.get("count", 0)) if info else 0

        # If already seen before, allow looser threshold; otherwise use strict.
        thr = loose_threshold if prev_count >= 1 else strict_threshold
        if conf > thr:
            continue

        new_count = prev_count + 1
        candidates[sid] = {"count": float(new_count), "last_seen": float(now), "best": float(conf)}
        if new_count >= confirm_frames:
            detected_ids.add(sid)
        else:
            pending_ids.add(sid)

    state["candidates"] = candidates

    newly_marked = 0
    for sid in detected_ids:
        obj, created = AttendanceRecord.objects.update_or_create(
            session=session,
            student_id=sid,
            defaults={"status": AttendanceRecord.STATUS_PRESENT, "source": "live_face"},
        )
        if created or obj.status != AttendanceRecord.STATUS_PRESENT:
            newly_marked += 1

    return JsonResponse(
        {
            "ok": True,
            "present_detected": len(detected_ids),
            "newly_marked": newly_marked,
            "pending": len(pending_ids),
            "faces_detected": len(recognized),
            "trained_faces": len(train_images),
            "trained_students": len(set(train_labels)),
            "top_matches": [{"id": int(i), "conf": float(c)} for (i, c) in top_matches],
            "eyes": int(eyes_count),
            "blink_recent": (now - float(state.get("last_blink_ts", 0.0)) <= 6.0),
        }
    )
