from django.conf import settings
from django.db import models

from attendance.models import Student


class FoodStall(models.Model):
    name = models.CharField(max_length=128, unique=True)
    location = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(default=True)
    max_items_per_day = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.name


class MenuCategory(models.Model):
    stall = models.ForeignKey(FoodStall, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=64)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("stall", "name")
        ordering = ["stall_id", "sort_order", "name"]

    def __str__(self) -> str:
        return f"{self.stall.name} - {self.name}"


class MenuItem(models.Model):
    stall = models.ForeignKey(FoodStall, on_delete=models.CASCADE, related_name="items")
    category = models.ForeignKey(
        MenuCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="items"
    )
    name = models.CharField(max_length=128)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)
    prep_time_minutes = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("stall", "name")
        ordering = ["stall_id", "name"]

    def __str__(self) -> str:
        return f"{self.stall.name} - {self.name}"


class BreakSlot(models.Model):
    label = models.CharField(max_length=64)
    slot_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("slot_date", "start_time", "end_time", "label")
        ordering = ["-slot_date", "start_time"]

    def __str__(self) -> str:
        return f"{self.label} {self.slot_date} {self.start_time}-{self.end_time}"


class SlotCapacity(models.Model):
    stall = models.ForeignKey(FoodStall, on_delete=models.CASCADE, related_name="capacities")
    break_slot = models.ForeignKey(BreakSlot, on_delete=models.CASCADE, related_name="capacities")
    max_items = models.PositiveIntegerField(default=0)
    is_open = models.BooleanField(default=True)

    class Meta:
        unique_together = ("stall", "break_slot")

    def __str__(self) -> str:
        return f"{self.stall.name} {self.break_slot}: {self.max_items}"


class FoodOrder(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_PREPARING = "preparing"
    STATUS_READY = "ready"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_PREPARING, "Preparing"),
        (STATUS_READY, "Ready"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    student = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True, related_name="food_orders"
    )
    ordered_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="food_orders",
    )
    ordered_by_label = models.CharField(max_length=128, blank=True)
    stall = models.ForeignKey(FoodStall, on_delete=models.CASCADE, related_name="orders")
    break_slot = models.ForeignKey(
        BreakSlot, on_delete=models.PROTECT, related_name="orders", null=True, blank=True
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        who = self.ordered_by_label
        if not who and self.ordered_by_user_id:
            who = getattr(self.ordered_by_user, "username", "")
        if not who and self.student_id:
            who = self.student.roll_no
        who = who or "Order"
        return f"Order #{self.id} {who} {self.stall.name}"

    @property
    def total_items(self) -> int:
        return int(sum((oi.qty for oi in self.items.all()), 0))

    @property
    def total_amount(self):
        return sum((oi.line_total for oi in self.items.all()), 0)


class FoodOrderItem(models.Model):
    order = models.ForeignKey(FoodOrder, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.order_id} {self.menu_item.name} x{self.qty}"

    @property
    def line_total(self):
        return self.unit_price * self.qty
