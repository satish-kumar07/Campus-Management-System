from django.contrib import admin

# Register your models here.

from .models import Classroom


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    change_list_template = "admin/classrooms/classroom/change_list.html"

    list_display = ("block", "room_number", "capacity", "room_type")
    list_filter = ("block", "room_type")
    search_fields = ("room_number", "block__name")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("block")

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            cl = response.context_data.get("cl")
            result_list = list(getattr(cl, "result_list", []) or [])
        except Exception:
            return response

        grouped = {}
        for obj in result_list:
            key = getattr(getattr(obj, "block", None), "name", "(No Block)")
            grouped.setdefault(key, []).append(obj)

        response.context_data["grouped_by_block"] = [(k, grouped[k]) for k in sorted(grouped.keys())]
        return response
