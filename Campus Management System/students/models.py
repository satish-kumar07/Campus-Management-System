from django.db import models


class Student(models.Model):
    registration_number = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.CASCADE,
        related_name="students",
    )

    def __str__(self) -> str:
        return f"{self.registration_number} - {self.name}"
