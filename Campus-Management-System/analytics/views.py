from django.shortcuts import render

from blocks.models import Block
from classrooms.models import Classroom
from faculty.models import Faculty


def dashboard_view(request):
    blocks = Block.objects.all().order_by("name")
    classrooms = Classroom.objects.select_related("block").all().order_by("block__name", "room_number")
    faculty = Faculty.objects.all().order_by("name")

    suggestions: list[str] = []

    for room in classrooms:
        try:
            util = float(room.utilization_percentage() or 0)
        except Exception:
            util = 0
        if util > 90:
            suggestions.append(f"{room.block.name} {room.room_number}: Consider assigning larger classroom")

    for f in faculty:
        try:
            if f.current_workload() > f.max_workload_hours:
                suggestions.append(f"{f.name}: Consider redistributing courses")
        except Exception:
            continue

    return render(
        request,
        "dashboard.html",
        {
            "blocks": blocks,
            "classrooms": classrooms,
            "faculty": faculty,
            "suggestions": suggestions,
        },
    )
