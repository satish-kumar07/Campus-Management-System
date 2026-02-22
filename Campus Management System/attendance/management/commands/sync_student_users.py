from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from attendance.models import Student


class Command(BaseCommand):
    help = "Link Student rows to Django User accounts (username=UID) and ensure STUDENT group. Does not reset passwords."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change, but do not write to DB.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))

        User = get_user_model()
        group, _ = Group.objects.get_or_create(name="STUDENT")

        linked = 0
        created = 0
        updated_username = 0
        added_group = 0
        skipped_no_uid = 0

        qs = Student.objects.select_related("user").order_by("id")

        with transaction.atomic():
            for s in qs:
                if s.uid is None:
                    skipped_no_uid += 1
                    continue

                username = str(s.uid)

                user = s.user
                if user is None:
                    user = User.objects.filter(username=username).first()

                if user is None:
                    created += 1
                    if dry_run:
                        continue
                    user = User(username=username)
                    if getattr(s, "email", ""):
                        user.email = s.email
                    user.save()

                if getattr(user, "username", "") != username:
                    updated_username += 1
                    if not dry_run:
                        user.username = username
                        user.save(update_fields=["username"])

                if not user.groups.filter(id=group.id).exists():
                    added_group += 1
                    if not dry_run:
                        user.groups.add(group)

                if s.user_id != user.id:
                    linked += 1
                    if not dry_run:
                        s.user = user
                        s.save(update_fields=["user"])

        self.stdout.write(self.style.SUCCESS("sync_student_users finished"))
        self.stdout.write(f"dry_run={dry_run}")
        self.stdout.write(f"created_users={created}")
        self.stdout.write(f"linked_students={linked}")
        self.stdout.write(f"updated_username={updated_username}")
        self.stdout.write(f"added_student_group={added_group}")
        self.stdout.write(f"skipped_no_uid={skipped_no_uid}")
