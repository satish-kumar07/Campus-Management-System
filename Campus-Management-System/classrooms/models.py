from django.db import models


class Classroom(models.Model):
    ROOM_TYPE_THEORY = "THEORY"
    ROOM_TYPE_LAB = "LAB"

    ROOM_TYPE_CHOICES = [
        (ROOM_TYPE_THEORY, "Theory"),
        (ROOM_TYPE_LAB, "Lab"),
    ]

    block = models.ForeignKey(
        "blocks.Block",
        on_delete=models.CASCADE,
        related_name="classrooms",
    )
    room_number = models.CharField(max_length=50)
    capacity = models.IntegerField()
    room_type = models.CharField(max_length=10, choices=ROOM_TYPE_CHOICES)

    class Meta:
        unique_together = ("block", "room_number")

    def __str__(self) -> str:
        block_name = getattr(getattr(self, "block", None), "name", "")
        room = getattr(self, "room_number", "")
        if block_name and room:
            return f"{block_name} - {room}"
        return room or f"Classroom {self.pk}"

    def utilization_percentage(self):
        total_students = sum((course.enrollments.count() for course in self.course_set.all()), 0)
        return (total_students / self.capacity) * 100 if self.capacity > 0 else 0
