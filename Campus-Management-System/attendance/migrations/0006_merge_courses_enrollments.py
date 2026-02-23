from django.db import migrations, models
import django.db.models.deletion


def _forwards(apps, schema_editor):
    AttendanceCourse = apps.get_model("attendance", "Course")
    AttendanceEnrollment = apps.get_model("attendance", "Enrollment")
    AttendanceSession = apps.get_model("attendance", "AttendanceSession")

    CoursesCourse = apps.get_model("courses", "Course")
    CoursesEnrollment = apps.get_model("courses", "Enrollment")

    # Map old attendance.Course -> courses.Course using code as the stable key.
    by_code: dict[str, int] = {}

    for c in AttendanceCourse.objects.all():
        code = (getattr(c, "code", "") or "").strip()
        name = (getattr(c, "name", "") or "").strip() or code
        if not code:
            continue

        obj = CoursesCourse.objects.filter(code=code).first()
        if obj is None:
            # courses.Course requires credits/weekly_hours; legacy attendance.Course did not have them.
            obj = CoursesCourse.objects.create(
                code=code,
                name=name,
                credits=0,
                weekly_hours=0,
            )
        by_code[code] = obj.pk

    # Rewire sessions to the consolidated course.
    for s in AttendanceSession.objects.select_related("course").all():
        old_course = getattr(s, "course", None)
        code = (getattr(old_course, "code", "") or "").strip()
        new_course_id = by_code.get(code)
        if new_course_id is None and code:
            # Fallback if a course row was missing in attendance.Course for some reason.
            obj = CoursesCourse.objects.filter(code=code).first()
            if obj is None:
                obj = CoursesCourse.objects.create(
                    code=code,
                    name=(getattr(old_course, "name", "") or "").strip() or code,
                    credits=0,
                    weekly_hours=0,
                )
            new_course_id = obj.pk
            by_code[code] = new_course_id

        if new_course_id is not None:
            s.course_new_id = new_course_id
            s.save(update_fields=["course_new"])

    # Migrate enrollments into courses.Enrollment (idempotent via unique_together).
    for e in AttendanceEnrollment.objects.select_related("course", "student").all():
        old_course = getattr(e, "course", None)
        code = (getattr(old_course, "code", "") or "").strip()
        new_course_id = by_code.get(code)
        if new_course_id is None:
            continue

        CoursesEnrollment.objects.get_or_create(
            student_id=e.student_id,
            course_id=new_course_id,
        )


def _backwards(apps, schema_editor):
    # Non-reversible: old attendance.Course/Enrollment data may have been deleted.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0005_student_uid_student_user"),
        ("courses", "0002_enrollment"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancesession",
            name="course_new",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="courses.course",
            ),
        ),
        migrations.RunPython(_forwards, _backwards),
        migrations.RemoveField(
            model_name="attendancesession",
            name="course",
        ),
        migrations.RenameField(
            model_name="attendancesession",
            old_name="course_new",
            new_name="course",
        ),
        migrations.DeleteModel(
            name="Enrollment",
        ),
        migrations.DeleteModel(
            name="Course",
        ),
    ]
