from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

import logging

import cv2
import numpy as np
from PIL import Image
from django.http import JsonResponse
import base64
import time
from collections import deque

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
    CourseCreateForm,
    EnrollmentForm,
    FaceSampleMultiForm,
    FaceSampleForm,
    StudentForm,
)
from .models import AttendanceRecord, AttendanceSession, Course, Enrollment, FaceSample, Notification, Student


_live_state: dict[tuple[int, int], dict[str, object]] = {}

logger = logging.getLogger(__name__)


def _send_absent_email(*, student: Student, session: AttendanceSession) -> tuple[bool, str]:
    recipients: list[str] = []
    parent_email = (getattr(student, "parent_email", "") or "").strip()
    student_email = (getattr(student, "email", "") or "").strip()
    if parent_email:
        recipients.append(parent_email)
    elif student_email:
        recipients.append(student_email)
    recipients = sorted({r for r in recipients if r})
    if not recipients:
        logger.info("Absent email not sent: missing recipient email for student_id=%s", student.id)
        return (False, "Missing parent/student email")
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
    if not from_email:
        logger.error("Absent email not sent: DEFAULT_FROM_EMAIL/EMAIL_HOST_USER not configured")
        return (False, "Email not configured (DEFAULT_FROM_EMAIL/EMAIL_HOST_USER)")
    subject = f"Attendance Alert: {student.full_name} marked absent ({session.course.code})"
    body = (
        "Dear Parent/Guardian,\n\n"
        f"This is to inform you that {student.full_name} (Roll No: {student.roll_no}) "
        f"was marked ABSENT for the course {session.course.code} on {session.session_date}."
    )
    if session.time_slot:
        body += f"\nTime slot: {session.time_slot}"
    if session.session_label:
        body += f"\nSession: {session.session_label}"
    body += (
        "\n\nIf you believe this is an error, please reply to this email or contact the administration.\n"
        "\nRegards,\nCMS Administration\n"
    )
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
def home(request: HttpRequest) -> HttpResponse:
    recent_sessions = AttendanceSession.objects.select_related("course").order_by("-created_at")[:3]
    stats = {
        "students": Student.objects.count(),
        "courses": Course.objects.count(),
        "enrollments": Enrollment.objects.count(),
        "face_samples": FaceSample.objects.count(),
        "sessions": AttendanceSession.objects.count(),
    }
    return render(
        request,
        "attendance/dashboard.html",
        {
            "recent_sessions": recent_sessions,
            "stats": stats,
        },
    )


@login_required
def attendance_home(request: HttpRequest) -> HttpResponse:
    sessions = AttendanceSession.objects.select_related("course").order_by("-created_at")[:20]
    return render(request, "attendance/attendance_home.html", {"sessions": sessions})


@login_required
def manage_dashboard(request: HttpRequest) -> HttpResponse:
    stats = {
        "students": Student.objects.count(),
        "courses": Course.objects.count(),
        "enrollments": Enrollment.objects.count(),
        "face_samples": FaceSample.objects.count(),
        "notifications": Notification.objects.count(),
        "sessions": AttendanceSession.objects.count(),
        "records": AttendanceRecord.objects.count(),
    }
    return render(request, "attendance/manage/dashboard.html", {"stats": stats})


@login_required
def manage_students(request: HttpRequest) -> HttpResponse:
    students = Student.objects.order_by("roll_no")
    return render(request, "attendance/manage/students.html", {"students": students})


@login_required
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
def manage_student_delete(request: HttpRequest, student_id: int) -> HttpResponse:
    student = get_object_or_404(Student, id=student_id)
    if request.method == "POST":
        student.delete()
        messages.success(request, "Student deleted.")
        return redirect("manage_students")
    return render(request, "attendance/manage/confirm_delete.html", {"object": student, "type": "Student"})


@login_required
def manage_courses(request: HttpRequest) -> HttpResponse:
    courses = Course.objects.order_by("code")
    return render(request, "attendance/manage/courses.html", {"courses": courses})


@login_required
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
def manage_course_delete(request: HttpRequest, course_id: int) -> HttpResponse:
    course = get_object_or_404(Course, id=course_id)
    if request.method == "POST":
        course.delete()
        messages.success(request, "Course deleted.")
        return redirect("manage_courses")
    return render(request, "attendance/manage/confirm_delete.html", {"object": course, "type": "Course"})


@login_required
def manage_enrollments(request: HttpRequest) -> HttpResponse:
    enrollments = Enrollment.objects.select_related("student", "course").order_by("course__code", "student__roll_no")
    return render(request, "attendance/manage/enrollments.html", {"enrollments": enrollments})


@login_required
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
def manage_face_samples(request: HttpRequest) -> HttpResponse:
    samples = FaceSample.objects.select_related("student").order_by("-created_at")
    return render(request, "attendance/manage/face_samples.html", {"samples": samples})


@login_required
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
def manage_notifications(request: HttpRequest) -> HttpResponse:
    notifications = Notification.objects.select_related("recipient_student").order_by("-created_at")[:200]
    return render(request, "attendance/manage/notifications.html", {"notifications": notifications})


@login_required
def manage_sessions(request: HttpRequest) -> HttpResponse:
    sessions = AttendanceSession.objects.select_related("course").order_by("-created_at")[:200]
    return render(request, "attendance/manage/sessions.html", {"sessions": sessions})


@login_required
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
    if request.method == "POST":
        form = AttendanceSessionCreateForm(request.POST)
        if form.is_valid():
            session = form.save()
            messages.success(request, "Session created.")
            return redirect("session_detail", session_id=session.id)
    else:
        now = timezone.localtime(timezone.now()).replace(second=0, microsecond=0) + timezone.timedelta(minutes=1)
        form = AttendanceSessionCreateForm(initial={"session_start_at": now})

    return render(request, "attendance/create_session.html", {"form": form})


@login_required
def edit_session(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    if request.method == "POST":
        form = AttendanceSessionCreateForm(request.POST, instance=session)
        if form.is_valid():
            form.save()
            messages.success(request, "Session updated.")
            return redirect("session_detail", session_id=session.id)
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
def session_detail(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    students = (
        Student.objects.filter(enrollments__course=session.course)
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
        "attendance/session_detail.html",
        {"session": session, "student_rows": student_rows, "photo_form": AttendancePhotoUploadForm()},
    )


@login_required
@transaction.atomic
def mark_attendance_by_photo(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    students = (
        Student.objects.filter(enrollments__course=session.course)
        .order_by("roll_no")
        .distinct()
    )

    if request.method != "POST":
        return redirect("session_detail", session_id=session.id)

    form = AttendancePhotoUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Please upload a valid image.")
        return redirect("session_detail", session_id=session.id)

    # Build training set from stored FaceSample images
    images_by_label: dict[int, list[np.ndarray]] = {}
    usable_counts: dict[int, int] = {}
    for fs in (
        FaceSample.objects.select_related("student")
        .filter(student__enrollments__course=session.course)
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
        return redirect("session_detail", session_id=session.id)

    # Decode uploaded image
    upload = form.cleaned_data["photo"]
    pil = Image.open(upload).convert("RGB")
    rgb = np.array(pil)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    recognized = recognize_faces_in_image(recognizer, bgr)

    # LBPH: lower confidence is better.
    # Strict mode (A1): use a tighter threshold to reduce false positives.
    threshold = 70.0
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

    # Ambiguity guard: if the best match isn't clearly better than the second best,
    # treat the image as unknown to prevent look-alike false positives.
    if len(sorted_matches) >= 2:
        best_conf = float(sorted_matches[0][1])
        second_conf = float(sorted_matches[1][1])
        if (second_conf - best_conf) < 12.0:
            messages.error(
                request,
                "Face match is ambiguous (two students are too close). Please try again with better lighting/angle or improve Face Data.",
            )
            return redirect("session_detail", session_id=session.id)

    present_ids = {sid for (sid, conf) in sorted_matches if conf <= threshold}

    for s in students:
        status = (
            AttendanceRecord.STATUS_PRESENT
            if s.id in present_ids
            else AttendanceRecord.STATUS_ABSENT
        )
        AttendanceRecord.objects.update_or_create(
            session=session,
            student=s,
            defaults={"status": status, "source": "face"},
        )

    absentees = [s for s in students if s.id not in present_ids]
    email_failures: list[str] = []
    for s in absentees:
        msg = (
            f"Absent detected: {s.full_name} ({s.roll_no}) was marked ABSENT for "
            f"{session.course.code} on {session.session_date}."
        )
        Notification.objects.create(recipient_student=s, channel="simulated", message=msg)
        ok, reason = _send_absent_email(student=s, session=session)
        if not ok:
            email_failures.append(f"{s.roll_no}: {reason}")

    messages.success(
        request,
        f"Photo-based marking complete. Detected present: {len(present_ids)} | Absentees: {len(absentees)}",
    )
    if email_failures:
        preview = "; ".join(email_failures[:3])
        extra = "" if len(email_failures) <= 3 else f" (+{len(email_failures) - 3} more)"
        messages.warning(request, f"Absent emails not sent for {len(email_failures)} student(s): {preview}{extra}")
    return redirect("session_detail", session_id=session.id)


@login_required
@transaction.atomic
def mark_attendance(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(AttendanceSession.objects.select_related("course"), id=session_id)
    students = (
        Student.objects.filter(enrollments__course=session.course)
        .order_by("roll_no")
        .distinct()
    )

    if request.method != "POST":
        return redirect("session_detail", session_id=session.id)

    action = request.POST.get("action", "")

    if action == "mark_all_present":
        for s in students:
            AttendanceRecord.objects.update_or_create(
                session=session,
                student=s,
                defaults={"status": AttendanceRecord.STATUS_PRESENT, "source": "manual"},
            )
        messages.success(request, "Marked all students present.")
        return redirect("session_detail", session_id=session.id)

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
    for s in absentees:
        msg = (
            f"Absent detected: {s.full_name} ({s.roll_no}) was marked ABSENT for "
            f"{session.course.code} on {session.session_date}."
        )
        Notification.objects.create(recipient_student=s, channel="simulated", message=msg)
        ok, reason = _send_absent_email(student=s, session=session)
        if not ok:
            email_failures.append(f"{s.roll_no}: {reason}")

    messages.success(request, f"Attendance saved. Absentees: {len(absentees)}")
    if email_failures:
        preview = "; ".join(email_failures[:3])
        extra = "" if len(email_failures) <= 3 else f" (+{len(email_failures) - 3} more)"
        messages.warning(request, f"Absent emails not sent for {len(email_failures)} student(s): {preview}{extra}")
    return redirect("session_detail", session_id=session.id)


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
        Student.objects.filter(enrollments__course=session.course)
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
        .filter(student__enrollments__course=session.course)
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
