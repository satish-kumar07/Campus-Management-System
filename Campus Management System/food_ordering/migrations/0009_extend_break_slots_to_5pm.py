from __future__ import annotations

import datetime

from django.db import migrations


def seed_extended_break_slots_and_capacities(apps, schema_editor) -> None:
    FoodStall = apps.get_model("food_ordering", "FoodStall")
    BreakSlot = apps.get_model("food_ordering", "BreakSlot")
    SlotCapacity = apps.get_model("food_ordering", "SlotCapacity")

    start_date = datetime.date.today()
    days_ahead = 14

    slot_start_time = datetime.time(9, 0)
    slot_end_limit = datetime.time(17, 0)
    step_minutes = 15
    duration_minutes = 10

    slots = []
    for day_offset in range(days_ahead):
        slot_date = start_date + datetime.timedelta(days=day_offset)
        cursor = datetime.datetime.combine(slot_date, slot_start_time)
        end_limit_dt = datetime.datetime.combine(slot_date, slot_end_limit)

        idx = 1
        while cursor < end_limit_dt:
            s = cursor
            e = s + datetime.timedelta(minutes=duration_minutes)
            label = f"Break Slot {idx}"

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

            idx += 1
            cursor = cursor + datetime.timedelta(minutes=step_minutes)

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


def noop_reverse(apps, schema_editor) -> None:
    return


class Migration(migrations.Migration):
    dependencies = [
        ("food_ordering", "0008_seed_default_break_slots_and_capacities"),
    ]

    operations = [
        migrations.RunPython(seed_extended_break_slots_and_capacities, reverse_code=noop_reverse),
    ]
