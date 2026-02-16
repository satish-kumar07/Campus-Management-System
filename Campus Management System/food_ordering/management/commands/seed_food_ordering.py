from django.core.management.base import BaseCommand
from django.utils import timezone

from food_ordering.models import FoodStall, MenuCategory, MenuItem


class Command(BaseCommand):
    help = "Seed food ordering demo data (stalls and menu)."

    def handle(self, *args, **options):
        timezone.localdate()

        stall1, _ = FoodStall.objects.get_or_create(
            name="North Canteen", defaults={"location": "Block A", "max_items_per_day": 0}
        )
        stall2, _ = FoodStall.objects.get_or_create(
            name="South Snacks", defaults={"location": "Block C", "max_items_per_day": 0}
        )
        stall3, _ = FoodStall.objects.get_or_create(
            name="Combo Canteen", defaults={"location": "Block B", "max_items_per_day": 0}
        )

        cat1, _ = MenuCategory.objects.get_or_create(stall=stall1, name="Meals", defaults={"sort_order": 1})
        cat2, _ = MenuCategory.objects.get_or_create(stall=stall1, name="Beverages", defaults={"sort_order": 2})

        MenuItem.objects.get_or_create(stall=stall1, category=cat1, name="Veg Thali", defaults={"price": 70, "is_available": True})
        MenuItem.objects.get_or_create(stall=stall1, category=cat1, name="Paneer Rice", defaults={"price": 80, "is_available": True})
        MenuItem.objects.get_or_create(stall=stall1, category=cat2, name="Tea", defaults={"price": 10, "is_available": True})
        MenuItem.objects.get_or_create(stall=stall1, category=cat2, name="Coffee", defaults={"price": 15, "is_available": True})

        MenuItem.objects.get_or_create(stall=stall2, name="Samosa", defaults={"price": 12, "is_available": True})
        MenuItem.objects.get_or_create(stall=stall2, name="Veg Puff", defaults={"price": 20, "is_available": True})
        MenuItem.objects.get_or_create(stall=stall2, name="Lemon Soda", defaults={"price": 25, "is_available": True})

        MenuItem.objects.get_or_create(stall=stall2, name="Burger Combo", defaults={"price": 99, "is_available": True})
        MenuItem.objects.get_or_create(stall=stall2, name="French Fries", defaults={"price": 45, "is_available": True})

        combo_cat, _ = MenuCategory.objects.get_or_create(
            stall=stall3, name="Combos", defaults={"sort_order": 1}
        )
        drinks_cat, _ = MenuCategory.objects.get_or_create(
            stall=stall3, name="Drinks", defaults={"sort_order": 2}
        )
        MenuItem.objects.get_or_create(
            stall=stall3,
            category=combo_cat,
            name="Paneer Roll Combo",
            defaults={"price": 120, "is_available": True},
        )
        MenuItem.objects.get_or_create(
            stall=stall3,
            category=combo_cat,
            name="Burger + Fries Combo",
            defaults={"price": 149, "is_available": True},
        )
        MenuItem.objects.get_or_create(
            stall=stall3,
            category=drinks_cat,
            name="Cold Coffee",
            defaults={"price": 60, "is_available": True},
        )

        self.stdout.write(self.style.SUCCESS("Seeded food ordering demo data."))
