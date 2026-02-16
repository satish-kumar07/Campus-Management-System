from django.contrib import admin

from .models import (
    BreakSlot,
    FoodOrder,
    FoodOrderItem,
    FoodStall,
    MenuCategory,
    MenuItem,
    SlotCapacity,
)


@admin.register(FoodStall)
class FoodStallAdmin(admin.ModelAdmin):
    list_display = ("name", "location", "is_active", "max_items_per_day")
    list_filter = ("is_active",)
    search_fields = ("name", "location")


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "stall", "sort_order")
    list_filter = ("stall",)
    search_fields = ("name",)


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("name", "stall", "category", "price", "is_available")
    list_filter = ("stall", "is_available", "category")
    search_fields = ("name",)


@admin.register(BreakSlot)
class BreakSlotAdmin(admin.ModelAdmin):
    list_display = ("label", "slot_date", "start_time", "end_time", "is_active")
    list_filter = ("slot_date", "is_active")
    search_fields = ("label",)


@admin.register(SlotCapacity)
class SlotCapacityAdmin(admin.ModelAdmin):
    list_display = ("stall", "break_slot", "max_items", "is_open")
    list_filter = ("stall", "is_open", "break_slot__slot_date")


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
        "created_at",
    )
    list_filter = ("status", "stall")
    search_fields = ("ordered_by_label", "ordered_by_user__username", "student__roll_no", "student__full_name")
    inlines = [FoodOrderItemInline]
