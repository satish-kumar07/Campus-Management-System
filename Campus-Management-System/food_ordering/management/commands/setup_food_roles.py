from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create default roles for Food Ordering (STUDENT, VENDOR)."

    def handle(self, *args, **options):
        Group.objects.get_or_create(name="STUDENT")
        Group.objects.get_or_create(name="VENDOR")
        self.stdout.write(self.style.SUCCESS("Created/verified groups: STUDENT, VENDOR"))
