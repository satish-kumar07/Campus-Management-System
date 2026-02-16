from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

from attendance.models import Student

from .forms import PreOrderForm
from .models import FoodOrder, FoodOrderItem, FoodStall, MenuCategory, MenuItem


def _get_current_student(request: HttpRequest):
    username = (getattr(request.user, "username", "") or "").strip()
    if not username:
        return None
    return Student.objects.filter(roll_no=username).first()


@login_required
def food_home(request: HttpRequest) -> HttpResponse:
    return render(request, "food_ordering/home.html")


@login_required
def stalls_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    stalls_qs = FoodStall.objects.filter(is_active=True)
    if q:
        stalls_qs = stalls_qs.filter(name__icontains=q)
    stalls = list(stalls_qs.order_by("name"))

    popular_by_stall: dict[int, list[str]] = {}
    if stalls:
        stall_ids = [s.id for s in stalls]
        items = (
            MenuItem.objects.filter(stall_id__in=stall_ids, is_available=True)
            .order_by("stall_id", "name")
            .values_list("stall_id", "name")
        )
        for sid, name in items:
            names = popular_by_stall.setdefault(int(sid), [])
            if len(names) < 3:
                names.append(str(name))

    stall_cards = [
        {
            "stall": s,
            "popular": popular_by_stall.get(int(s.id), []),
        }
        for s in stalls
    ]

    return render(
        request,
        "food_ordering/stalls_list.html",
        {
            "q": q,
            "stall_cards": stall_cards,
            "today_special": "Today's Special: North Canteen – Free Cold Drink on Orders Above ₹120",
        },
    )


@login_required
def stall_menu(request: HttpRequest, stall_id: int) -> HttpResponse:
    stall = get_object_or_404(FoodStall, pk=stall_id, is_active=True)
    categories = (
        MenuCategory.objects.filter(stall=stall)
        .prefetch_related("items")
        .order_by("sort_order", "name")
    )
    uncategorized_items = MenuItem.objects.filter(stall=stall, category__isnull=True).order_by("name")
    return render(
        request,
        "food_ordering/stall_menu.html",
        {
            "stall": stall,
            "categories": categories,
            "uncategorized_items": uncategorized_items,
        },
    )


def _parse_item_quantities(request: HttpRequest, items_qs):
    selected: list[tuple[MenuItem, int]] = []
    total_qty = 0
    for it in items_qs:
        raw = (request.POST.get(f"qty_{it.id}") or "").strip()
        if raw == "":
            continue
        try:
            qty = int(raw)
        except ValueError:
            qty = 0
        if qty <= 0:
            continue
        selected.append((it, qty))
        total_qty += qty
    return selected, total_qty


@login_required
def preorder(request: HttpRequest, stall_id: int) -> HttpResponse:
    stall = get_object_or_404(FoodStall, pk=stall_id, is_active=True)
    student = _get_current_student(request)
    items = MenuItem.objects.filter(stall=stall, is_available=True).order_by("name")

    if request.method == "POST":
        form = PreOrderForm(request.POST)
        selected, requested_items = _parse_item_quantities(request, items)
        if not selected:
            form.add_error(None, "Please select at least one item.")

        if form.is_valid() and selected:
            max_items_per_day = int(getattr(stall, "max_items_per_day", 0) or 0)
            if max_items_per_day > 0:
                today = timezone.localdate()
                already_items = (
                    FoodOrderItem.objects.filter(
                        order__stall=stall,
                        order__created_at__date=today,
                    )
                    .exclude(order__status=FoodOrder.STATUS_CANCELLED)
                    .aggregate(total=Sum("qty"))
                    .get("total")
                    or 0
                )
                if int(already_items) + int(requested_items) > max_items_per_day:
                    form.add_error(
                        None,
                        f"Daily capacity exceeded. Remaining items today: {max(max_items_per_day - int(already_items), 0)}",
                    )

            if form.is_valid() and selected and not form.errors:
                with transaction.atomic():
                    order = FoodOrder.objects.create(
                        student=student,
                        ordered_by_user=(request.user if getattr(request.user, "is_authenticated", False) else None),
                        ordered_by_label=(getattr(request.user, "username", "") or "").strip(),
                        stall=stall,
                    )
                    for it, qty in selected:
                        FoodOrderItem.objects.create(
                            order=order,
                            menu_item=it,
                            qty=qty,
                            unit_price=it.price,
                        )
                messages.success(request, f"Order #{order.id} placed successfully.")
                return redirect("food_my_orders")
    else:
        form = PreOrderForm()

    return render(
        request,
        "food_ordering/preorder.html",
        {
            "stall": stall,
            "items": items,
            "form": form,
        },
    )


@login_required
def my_orders(request: HttpRequest) -> HttpResponse:
    student = _get_current_student(request)
    qs = FoodOrder.objects.select_related("stall").prefetch_related("items", "items__menu_item")
    if getattr(request.user, "is_authenticated", False):
        orders = qs.filter(ordered_by_user=request.user).order_by("-created_at")
    elif student is not None:
        orders = qs.filter(student=student).order_by("-created_at")
    else:
        orders = qs.none()
    return render(
        request,
        "food_ordering/my_orders.html",
        {
            "orders": orders,
            "student": student,
        },
    )
