from django.contrib import admin

from django.db.models import QuerySet

from .models import (
    BreakSlot,
    FoodOrder,
    FoodOrderItem,
    FoodStall,
    MealDeal,
    MenuCategory,
    MenuItem,
    PickupSlotHold,
    SlotCapacity,
)


@admin.register(FoodStall)
class FoodStallAdmin(admin.ModelAdmin):
    list_display = ("name", "location", "image", "is_active", "max_items_per_day")
    list_filter = ("is_active",)
    search_fields = ("name", "location")
    filter_horizontal = ("operators",)


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "stall", "sort_order")
    list_filter = ("stall",)
    search_fields = ("name",)
    filter_horizontal = ("operators",)


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "stall", "category", "price", "is_available")
    list_filter = ("stall", "category", "is_available")
    search_fields = ("name", "description")
    list_editable = ("price", "is_available")
    ordering = ("stall", "category", "name")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "category":
            qs: QuerySet[MenuCategory] = MenuCategory.objects.select_related("stall").all()
            obj_id = None
            if request is not None and getattr(request, "resolver_match", None) is not None:
                obj_id = request.resolver_match.kwargs.get("object_id")

            if obj_id:
                try:
                    item = MenuItem.objects.filter(pk=obj_id).only("stall_id").first()
                    if item and item.stall_id:
                        qs = qs.filter(stall_id=item.stall_id)
                except Exception:
                    pass
            else:
                # When adding a new item, show all categories grouped by stall
                qs = qs

            # Customize label to show "Category Name (Stall Name)"
            kwargs["queryset"] = qs
            kwargs["label_from_instance"] = lambda obj: f"{obj.name} ({obj.stall.name})"
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(BreakSlot)
class BreakSlotAdmin(admin.ModelAdmin):
    list_display = ("label", "slot_date", "start_time", "end_time", "is_active")
    list_filter = ("slot_date", "is_active")
    search_fields = ("label",)


@admin.register(SlotCapacity)
class SlotCapacityAdmin(admin.ModelAdmin):
    list_display = ("stall", "break_slot", "max_orders", "max_items", "is_open")
    list_filter = ("stall", "is_open", "break_slot__slot_date")


@admin.register(PickupSlotHold)
class PickupSlotHoldAdmin(admin.ModelAdmin):
    list_display = ("stall", "break_slot", "user", "total_items", "expires_at", "is_consumed", "created_at")
    list_filter = ("stall", "is_consumed", "break_slot__slot_date")
    search_fields = ("user__username",)


@admin.register(MealDeal)
class MealDealAdmin(admin.ModelAdmin):
    list_display = ("name", "stall", "deal_price", "original_price", "is_active", "valid_from", "valid_until")
    list_filter = ("stall", "is_active", "valid_from", "valid_until")
    search_fields = ("name", "description")
    filter_horizontal = ("items",)
    date_hierarchy = "valid_from"


class FoodOrderItemInline(admin.TabularInline):
    model = FoodOrderItem
    extra = 0


@admin.register(FoodOrder)
class FoodOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ordered_by_user",
        "ordered_by_label",
        "student",
        "stall",
        "break_slot",
        "status",
        "pickup_code",
        "created_at",
    )
    list_filter = ("status", "stall")
    search_fields = ("ordered_by_label", "ordered_by_user__username", "student__roll_no", "student__full_name")
    inlines = [FoodOrderItemInline]
