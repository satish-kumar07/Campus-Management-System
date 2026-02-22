from __future__ import annotations

import datetime

from django.db import migrations


def seed_break_slots_and_capacities(apps, schema_editor) -> None:
    FoodStall = apps.get_model("food_ordering", "FoodStall")
    BreakSlot = apps.get_model("food_ordering", "BreakSlot")
    SlotCapacity = apps.get_model("food_ordering", "SlotCapacity")

    # Create 10 default slots per day for the next 14 days (including today).
    # Note: BreakSlot is global (not per stall). Per-stall availability is controlled by SlotCapacity.
    start_date = datetime.date.today()
    days_ahead = 14

    slots = []
    for day_offset in range(days_ahead):
        slot_date = start_date + datetime.timedelta(days=day_offset)
        start_dt = datetime.datetime.combine(slot_date, datetime.time(9, 0))
        for idx in range(10):
            s = start_dt + datetime.timedelta(minutes=15 * idx)
            e = s + datetime.timedelta(minutes=10)
            label = f"Break Slot {idx + 1}"

            slot, _ = BreakSlot.objects.get_or_create(
                label=label,
                slot_date=slot_date,
                start_time=s.time(),
                end_time=e.time(),
                defaults={"is_active": True},
            )
            if not slot.is_active:
                slot.is_active = True
                slot.save(update_fields=["is_active"])
            slots.append(slot)

    stalls = list(FoodStall.objects.all())
    for stall in stalls:
        for slot in slots:
            SlotCapacity.objects.get_or_create(
                stall=stall,
                break_slot=slot,
                defaults={
                    "max_orders": 50,
                    "max_items": 200,
                    "is_open": True,
                },
            )


def unseed_break_slots_and_capacities(apps, schema_editor) -> None:
    # Reverse does nothing intentionally. We should not delete operational data.
    return


class Migration(migrations.Migration):
    dependencies = [
        ("food_ordering", "0007_mealdeal"),
    ]

    operations = [
        migrations.RunPython(seed_break_slots_and_capacities, reverse_code=unseed_break_slots_and_capacities),
    ]
