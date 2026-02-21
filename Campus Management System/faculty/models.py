from django.db import models


class Faculty(models.Model):
    name = models.CharField(max_length=200)
    department = models.CharField(max_length=200)
    max_workload_hours = models.IntegerField(default=20)
    email = models.EmailField(unique=True)

    def __str__(self) -> str:
        return self.name

    def current_workload(self):
        return sum((course.weekly_hours for course in self.course_set.all()), 0)

    def workload_status(self):
        workload = self.current_workload()
        if workload > self.max_workload_hours:
            return "Overloaded"
        if workload == self.max_workload_hours:
            return "Balanced"
        return "Underloaded"
