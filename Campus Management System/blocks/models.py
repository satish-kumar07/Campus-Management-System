from django.db import models


class Block(models.Model):
    name = models.CharField(max_length=100, unique=True)
    total_floors = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

    def total_capacity(self):
        return sum((room.capacity for room in self.classrooms.all()), 0)

    def total_students(self):
        return sum(
            student_count
            for room in self.classrooms.all()
            for course in room.course_set.all()
            for student_count in [course.enrollments.count()]
        )

    def utilization_percentage(self):
        capacity = self.total_capacity()
        return (self.total_students() / capacity) * 100 if capacity > 0 else 0
