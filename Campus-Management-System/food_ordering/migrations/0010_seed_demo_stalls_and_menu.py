from __future__ import annotations

from decimal import Decimal

from django.db import migrations


def seed_demo_stalls_and_menu(apps, schema_editor) -> None:
    FoodStall = apps.get_model("food_ordering", "FoodStall")
    MenuCategory = apps.get_model("food_ordering", "MenuCategory")
    MenuItem = apps.get_model("food_ordering", "MenuItem")
    BreakSlot = apps.get_model("food_ordering", "BreakSlot")
    SlotCapacity = apps.get_model("food_ordering", "SlotCapacity")

    if FoodStall.objects.exists():
        return

    stalls = []

    def mk_stall(name: str, location: str):
        s = FoodStall.objects.create(
            name=name,
            location=location,
            is_active=True,
            max_items_per_day=0,
        )
        stalls.append(s)
        return s

    north = mk_stall("North Canteen", "Main Building - Ground Floor")
    south = mk_stall("South Canteen", "Hostel Block - Near Gate")
    juice = mk_stall("Juice Corner", "Academic Block - Lobby")
    snack = mk_stall("Snack Hub", "Sports Complex")

    def mk_cat(stall, name: str, sort: int):
        c, _ = MenuCategory.objects.get_or_create(stall=stall, name=name, defaults={"sort_order": sort})
        if c.sort_order != sort:
            c.sort_order = sort
            c.save(update_fields=["sort_order"])
        return c

    def mk_item(stall, category, name: str, price: str, prep: int | None = None):
        defaults = {
            "price": Decimal(price),
            "is_available": True,
            "prep_time_minutes": prep,
            "category": category,
        }
        MenuItem.objects.get_or_create(stall=stall, name=name, defaults=defaults)

    c = mk_cat(north, "Meals", 1)
    mk_item(north, c, "Veg Thali", "80.00", 10)
    mk_item(north, c, "Paneer Thali", "110.00", 12)
    mk_item(north, c, "Rajma Rice", "70.00", 8)

    c = mk_cat(north, "Snacks", 2)
    mk_item(north, c, "Samosa (2 pcs)", "20.00", 3)
    mk_item(north, c, "Vada Pav", "25.00", 4)
    mk_item(north, c, "Masala Maggi", "45.00", 7)

    c = mk_cat(south, "South Indian", 1)
    mk_item(south, c, "Idli (4 pcs)", "35.00", 6)
    mk_item(south, c, "Masala Dosa", "60.00", 10)
    mk_item(south, c, "Uttapam", "55.00", 10)

    c = mk_cat(south, "Beverages", 2)
    mk_item(south, c, "Tea", "12.00", 2)
    mk_item(south, c, "Coffee", "18.00", 3)

    c = mk_cat(juice, "Fresh Juices", 1)
    mk_item(juice, c, "Orange Juice", "45.00", 4)
    mk_item(juice, c, "Watermelon Juice", "40.00", 4)
    mk_item(juice, c, "Pineapple Juice", "50.00", 4)

    c = mk_cat(juice, "Shakes", 2)
    mk_item(juice, c, "Cold Coffee", "55.00", 5)
    mk_item(juice, c, "Chocolate Shake", "65.00", 6)

    c = mk_cat(snack, "Fast Food", 1)
    mk_item(snack, c, "Veg Burger", "55.00", 10)
    mk_item(snack, c, "Cheese Sandwich", "50.00", 8)
    mk_item(snack, c, "French Fries", "45.00", 7)

    c = mk_cat(snack, "Combos", 2)
    mk_item(snack, c, "Burger + Fries Combo", "95.00", 12)

    slots = list(BreakSlot.objects.filter(is_active=True))
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
        ("food_ordering", "0009_extend_break_slots_to_5pm"),
    ]

    operations = [
        migrations.RunPython(seed_demo_stalls_and_menu, reverse_code=noop_reverse),
    ]
