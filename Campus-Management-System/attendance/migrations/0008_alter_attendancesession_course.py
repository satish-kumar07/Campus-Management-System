from django.db import migrations, models
import django.db.models.deletion


def _delete_orphan_sessions(apps, schema_editor):
    AttendanceSession = apps.get_model("attendance", "AttendanceSession")
    AttendanceSession.objects.filter(course__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0007_add_subject_classroom_models"),
    ]

    operations = [
        migrations.RunPython(_delete_orphan_sessions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="attendancesession",
            name="course",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="courses.course"),
        ),
    ]
