from django.contrib import admin

# Register your models here.

from .models import Course, Enrollment


admin.site.register(Course)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    change_list_template = "admin/courses/enrollment/change_list.html"

    list_display = ("course", "student_roll_no", "student_full_name")
    list_filter = ("course",)
    search_fields = ("course__code", "course__name", "student__roll_no", "student__full_name")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("course", "student")

    @admin.display(ordering="student__roll_no", description="Roll No")
    def student_roll_no(self, obj: Enrollment):
        return getattr(getattr(obj, "student", None), "roll_no", "")

    @admin.display(ordering="student__full_name", description="Student")
    def student_full_name(self, obj: Enrollment):
        return getattr(getattr(obj, "student", None), "full_name", "")

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            cl = response.context_data.get("cl")
            result_list = list(getattr(cl, "result_list", []) or [])
        except Exception:
            return response

        grouped = {}
        for obj in result_list:
            course = getattr(obj, "course", None)
            key = str(course) if course is not None else "(No Course)"
            grouped.setdefault(key, []).append(obj)

        response.context_data["grouped_by_course"] = [(k, grouped[k]) for k in sorted(grouped.keys())]
        return response
