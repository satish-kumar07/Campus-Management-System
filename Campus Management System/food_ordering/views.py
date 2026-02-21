import random
import secrets

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

from attendance.models import Student

from .forms import PreOrderForm
from .authz import require_student, require_vendor
from .models import BreakSlot, FoodOrder, FoodOrderItem, FoodStall, MealDeal, MenuCategory, MenuItem, PickupSlotHold, SlotCapacity


def _get_daily_recommendations() -> list[MenuItem]:
    """Get random daily recommendations (consistent throughout the day)."""
    today = timezone.localdate().isoformat()
    cache_key = f"daily_food_recommendations_{today}"

    recommendations = cache.get(cache_key)
    if recommendations is not None:
        return recommendations

    # Pick 3 random available items using today's date as seed
    available_items = list(MenuItem.objects.filter(is_available=True).select_related("stall"))

    if len(available_items) <= 3:
        recommendations = available_items
    else:
        # Use today's date as seed for consistent results throughout the day
        random.seed(today)
        recommendations = random.sample(available_items, 3)
        random.seed()  # Reset seed

    cache.set(cache_key, recommendations, timeout=86400)  # 24 hours
    return recommendations


def _get_daily_meal_deals():
    """Get active meal deals for today."""
    today = timezone.localdate()
    return list(
        MealDeal.objects.filter(
            is_active=True,
            valid_from__lte=today,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .select_related("stall")
        .prefetch_related("items")[:3]
    )


def _get_current_student(request: HttpRequest):
    username = (getattr(request.user, "username", "") or "").strip()
    if not username:
        return None
    return Student.objects.filter(roll_no=username).first()


@login_required
@require_student
def food_home(request: HttpRequest) -> HttpResponse:
    is_vendor = bool(getattr(request.user, "groups", None) and request.user.groups.filter(name="VENDOR").exists())
    daily_recommendations = _get_daily_recommendations()
    daily_meal_deals = _get_daily_meal_deals()
    return render(
        request,
        "food_ordering/home.html",
        {
            "is_vendor": is_vendor,
            "daily_recommendations": daily_recommendations,
            "daily_meal_deals": daily_meal_deals,
        },
    )


@login_required
@require_student
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
            "cart": _get_cart_from_session(request),
        },
    )


@login_required
@require_student
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


def _get_cart_from_session(request: HttpRequest) -> dict:
    """Get all cart items from session across all stalls."""
    cart_items = []
    total_amount = 0
    total_qty = 0
    stall_id = None
    stall_name = None
    
    # Check all session keys for cart data
    for key in list(request.session.keys()):
        if key.startswith("food_preorder_"):
            payload = request.session.get(key, {})
            if not payload or not isinstance(payload, dict):
                continue
            
            items_data = payload.get("items", {})
            if not items_data:
                continue
            
            # Extract stall_id from key
            try:
                sid = int(key.replace("food_preorder_", ""))
                if stall_id is None:
                    stall_id = sid
                    try:
                        stall = FoodStall.objects.get(id=sid)
                        stall_name = stall.name
                    except FoodStall.DoesNotExist:
                        stall_name = "Unknown"
            except ValueError:
                continue
            
            # Get item details
            for item_id, qty in items_data.items():
                try:
                    item = MenuItem.objects.select_related("stall").get(id=int(item_id))
                    line_total = item.price * int(qty)
                    cart_items.append({
                        "item": item,
                        "qty": int(qty),
                        "line_total": line_total,
                    })
                    total_amount += line_total
                    total_qty += int(qty)
                except (MenuItem.DoesNotExist, ValueError):
                    continue
    
    return {
        "items": cart_items,
        "total_amount": total_amount,
        "total_qty": total_qty,
        "stall_id": stall_id,
        "stall_name": stall_name,
        "has_items": len(cart_items) > 0,
    }


def _preorder_session_key(stall_id: int) -> str:
    return f"food_preorder_{int(stall_id)}"


def _get_preorder_payload(request: HttpRequest, stall_id: int) -> dict:
    return dict(request.session.get(_preorder_session_key(stall_id), {}) or {})


def _set_preorder_payload(request: HttpRequest, stall_id: int, payload: dict) -> None:
    request.session[_preorder_session_key(stall_id)] = payload
    request.session.modified = True


def _clear_preorder_payload(request: HttpRequest, stall_id: int) -> None:
    key = _preorder_session_key(stall_id)
    if key in request.session:
        del request.session[key]
        request.session.modified = True


def _get_selected_items_from_payload(stall: FoodStall, payload: dict) -> tuple[list[tuple[MenuItem, int]], int]:
    raw_items = payload.get("items") or {}
    if not isinstance(raw_items, dict):
        return [], 0
    item_ids: list[int] = []
    qty_by_id: dict[int, int] = {}
    for k, v in raw_items.items():
        try:
            iid = int(k)
            qty = int(v)
        except Exception:
            continue
        if iid <= 0 or qty <= 0:
            continue
        item_ids.append(iid)
        qty_by_id[iid] = qty

    if not item_ids:
        return [], 0

    items = list(MenuItem.objects.filter(stall=stall, id__in=item_ids, is_available=True))
    selected: list[tuple[MenuItem, int]] = []
    total_qty = 0
    for it in items:
        qty = int(qty_by_id.get(int(it.id), 0) or 0)
        if qty <= 0:
            continue
        selected.append((it, qty))
        total_qty += qty
    return selected, total_qty


def _compute_prep_minutes(selected: list[tuple[MenuItem, int]]) -> int:
    mins = 0
    for it, _qty in selected:
        try:
            mins = max(mins, int(getattr(it, "prep_time_minutes", 0) or 0))
        except Exception:
            continue
    return int(mins)


def _slot_start_dt(slot: BreakSlot):
    return timezone.make_aware(timezone.datetime.combine(slot.slot_date, slot.start_time))


def _active_holds_qs(stall: FoodStall):
    now = timezone.now()
    return PickupSlotHold.objects.filter(stall=stall, is_consumed=False, expires_at__gt=now)


def _capacity_snapshot(stall: FoodStall, slot: BreakSlot) -> dict:
    cap = SlotCapacity.objects.filter(stall=stall, break_slot=slot).first()
    if not cap or not cap.is_open:
        return {
            "is_open": False,
            "max_orders": 0,
            "max_items": 0,
            "used_orders": 0,
            "used_items": 0,
            "remaining_orders": 0,
            "remaining_items": 0,
        }

    used_orders = (
        FoodOrder.objects.filter(stall=stall, break_slot=slot)
        .exclude(status=FoodOrder.STATUS_CANCELLED)
        .count()
    )
    used_items = (
        FoodOrderItem.objects.filter(order__stall=stall, order__break_slot=slot)
        .exclude(order__status=FoodOrder.STATUS_CANCELLED)
        .aggregate(total=Sum("qty"))
        .get("total")
        or 0
    )

    hold_qs = _active_holds_qs(stall).filter(break_slot=slot)
    hold_orders = hold_qs.count()
    hold_items = hold_qs.aggregate(total=Sum("total_items")).get("total") or 0

    used_orders = int(used_orders) + int(hold_orders)
    used_items = int(used_items) + int(hold_items)

    max_orders = int(getattr(cap, "max_orders", 0) or 0)
    max_items = int(getattr(cap, "max_items", 0) or 0)

    remaining_orders = max(max_orders - used_orders, 0) if max_orders > 0 else 10**9
    remaining_items = max(max_items - used_items, 0) if max_items > 0 else 10**9

    return {
        "is_open": True,
        "max_orders": max_orders,
        "max_items": max_items,
        "used_orders": used_orders,
        "used_items": used_items,
        "remaining_orders": int(remaining_orders),
        "remaining_items": int(remaining_items),
    }


@login_required
@require_student
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
                payload = {
                    "items": {str(it.id): int(qty) for it, qty in selected},
                    "requested_items": int(requested_items),
                    "created_at": timezone.now().isoformat(),
                }
                _set_preorder_payload(request, stall.id, payload)
                return redirect("food_select_pickup_slot", stall_id=stall.id)
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
@require_student
def select_pickup_slot(request: HttpRequest, stall_id: int) -> HttpResponse:
    stall = get_object_or_404(FoodStall, pk=stall_id, is_active=True)
    payload = _get_preorder_payload(request, stall.id)
    selected, requested_items = _get_selected_items_from_payload(stall, payload)
    if not selected:
        messages.error(request, "Please select items first.")
        return redirect("food_preorder", stall_id=stall.id)

    prep_minutes = _compute_prep_minutes(selected)
    now = timezone.now()
    today = timezone.localdate()

    slots = list(
        BreakSlot.objects.filter(is_active=True, slot_date__gte=today).order_by("slot_date", "start_time")
    )

    slot_cards: list[dict] = []
    for slot in slots:
        snap = _capacity_snapshot(stall, slot)
        feasible = True
        try:
            start_dt = _slot_start_dt(slot)
            if prep_minutes > 0 and now + timezone.timedelta(minutes=prep_minutes) > start_dt:
                feasible = False
        except Exception:
            feasible = False

        can_fit = snap["is_open"] and feasible
        if can_fit:
            if snap["remaining_orders"] < 1:
                can_fit = False
            if snap["remaining_items"] < int(requested_items):
                can_fit = False

        slot_cards.append(
            {
                "slot": slot,
                "is_open": snap["is_open"],
                "feasible": feasible,
                "can_fit": can_fit,
                "remaining_items": snap["remaining_items"],
                "remaining_orders": snap["remaining_orders"],
            }
        )

    suggestions: list[dict] = []
    if request.method == "POST":
        raw_slot_id = (request.POST.get("break_slot_id") or "").strip()
        try:
            slot_id = int(raw_slot_id)
        except Exception:
            slot_id = 0

        chosen = None
        for c in slot_cards:
            if int(getattr(c["slot"], "id", 0) or 0) == slot_id:
                chosen = c
                break

        if not chosen:
            messages.error(request, "Invalid slot selection.")
        elif not chosen["can_fit"]:
            idx = slot_cards.index(chosen)
            suggestions = [c for c in slot_cards[idx + 1 :] if c["can_fit"]][:3]
            messages.error(request, "Slot Full. Please choose another slot.")
        else:
            with transaction.atomic():
                active_existing = (
                    PickupSlotHold.objects.select_for_update()
                    .filter(stall=stall, user=request.user, is_consumed=False, expires_at__gt=timezone.now())
                    .order_by("-created_at")
                    .first()
                )
                if active_existing:
                    active_existing.is_consumed = True
                    active_existing.save(update_fields=["is_consumed"])

                hold = PickupSlotHold.objects.create(
                    stall=stall,
                    break_slot=chosen["slot"],
                    user=request.user,
                    total_items=int(requested_items),
                    expires_at=timezone.now() + timezone.timedelta(minutes=5),
                )
                payload["hold_id"] = int(hold.id)
                _set_preorder_payload(request, stall.id, payload)
            return redirect("food_confirm_pickup_slot", stall_id=stall.id)

    return render(
        request,
        "food_ordering/select_pickup_slot.html",
        {
            "stall": stall,
            "selected": selected,
            "requested_items": requested_items,
            "prep_minutes": prep_minutes,
            "slot_cards": slot_cards,
            "suggestions": suggestions,
        },
    )


@login_required
@require_student
def confirm_pickup_slot(request: HttpRequest, stall_id: int) -> HttpResponse:
    stall = get_object_or_404(FoodStall, pk=stall_id, is_active=True)
    student = _get_current_student(request)
    payload = _get_preorder_payload(request, stall.id)
    selected, requested_items = _get_selected_items_from_payload(stall, payload)
    hold_id = payload.get("hold_id")

    if not selected:
        messages.error(request, "Please select items first.")
        return redirect("food_preorder", stall_id=stall.id)

    try:
        hold_id_int = int(hold_id)
    except Exception:
        hold_id_int = 0

    hold = None
    if hold_id_int > 0:
        hold = PickupSlotHold.objects.select_related("break_slot").filter(id=hold_id_int, stall=stall, user=request.user).first()

    if not hold or hold.is_consumed or hold.expires_at <= timezone.now():
        messages.error(request, "Pickup slot hold expired. Please select a slot again.")
        payload.pop("hold_id", None)
        _set_preorder_payload(request, stall.id, payload)
        return redirect("food_select_pickup_slot", stall_id=stall.id)

    if request.method == "POST":
        with transaction.atomic():
            hold_locked = (
                PickupSlotHold.objects.select_for_update()
                .select_related("break_slot")
                .filter(id=hold.id, stall=stall, user=request.user)
                .first()
            )
            if not hold_locked or hold_locked.is_consumed or hold_locked.expires_at <= timezone.now():
                messages.error(request, "Pickup slot hold expired. Please select a slot again.")
                payload.pop("hold_id", None)
                _set_preorder_payload(request, stall.id, payload)
                return redirect("food_select_pickup_slot", stall_id=stall.id)

            snap = _capacity_snapshot(stall, hold_locked.break_slot)
            if not snap["is_open"] or snap["remaining_orders"] < 1 or snap["remaining_items"] < int(requested_items):
                messages.error(request, "Slot Full. Please choose another slot.")
                payload.pop("hold_id", None)
                _set_preorder_payload(request, stall.id, payload)
                return redirect("food_select_pickup_slot", stall_id=stall.id)

            pickup_code = secrets.token_hex(3).upper()
            order = FoodOrder.objects.create(
                student=student,
                ordered_by_user=(request.user if getattr(request.user, "is_authenticated", False) else None),
                ordered_by_label=(getattr(request.user, "username", "") or "").strip(),
                stall=stall,
                break_slot=hold_locked.break_slot,
                pickup_code=pickup_code,
            )
            for it, qty in selected:
                FoodOrderItem.objects.create(
                    order=order,
                    menu_item=it,
                    qty=qty,
                    unit_price=it.price,
                )

            hold_locked.is_consumed = True
            hold_locked.save(update_fields=["is_consumed"])

        _clear_preorder_payload(request, stall.id)
        messages.success(request, f"Order #{order.id} placed successfully.")
        return redirect("food_order_confirmation", order_id=order.id)

    remaining_seconds = max(int((hold.expires_at - timezone.now()).total_seconds()), 0)
    return render(
        request,
        "food_ordering/confirm_pickup_slot.html",
        {
            "stall": stall,
            "hold": hold,
            "selected": selected,
            "requested_items": requested_items,
            "remaining_seconds": remaining_seconds,
        },
    )


@login_required
@require_student
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


@login_required
@require_student
def order_confirmation(request: HttpRequest, order_id: int) -> HttpResponse:
    qs = FoodOrder.objects.select_related("stall").prefetch_related("items", "items__menu_item")
    order = get_object_or_404(qs, pk=order_id)
    if order.ordered_by_user_id != request.user.id:
        messages.error(request, "Not authorized to view this order.")
        return redirect("food_my_orders")
    return render(request, "food_ordering/order_confirmation.html", {"order": order})


@login_required
@require_vendor
def vendor_dashboard(request: HttpRequest) -> HttpResponse:
    categories = MenuCategory.objects.filter(operators=request.user, stall__is_active=True).select_related("stall").order_by(
        "stall__name", "sort_order", "name"
    )
    stalls_from_categories = FoodStall.objects.filter(categories__in=categories, is_active=True)
    stalls_from_stall_ops = FoodStall.objects.filter(operators=request.user, is_active=True)
    stalls = (stalls_from_categories | stalls_from_stall_ops).distinct().order_by("name")
    orders = (
        FoodOrder.objects.select_related("stall")
        .prefetch_related("items", "items__menu_item")
        .filter(stall__in=stalls)
        .exclude(status__in=[FoodOrder.STATUS_CANCELLED, FoodOrder.STATUS_COMPLETED])
        .order_by("created_at")
    )
    return render(
        request,
        "food_ordering/vendor_dashboard.html",
        {
            "stalls": stalls,
            "categories": categories,
            "orders": orders,
        },
    )


@login_required
@require_vendor
def vendor_update_order(request: HttpRequest, order_id: int) -> HttpResponse:
    order = get_object_or_404(FoodOrder.objects.select_related("stall"), pk=order_id)
    is_category_operator = MenuCategory.objects.filter(stall=order.stall, operators=request.user).exists()
    is_stall_operator = order.stall.operators.filter(id=request.user.id).exists()
    if not (is_category_operator or is_stall_operator):
        messages.error(request, "Not authorized for this stall.")
        return redirect("food_vendor_dashboard")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action in {FoodOrder.STATUS_ACCEPTED, FoodOrder.STATUS_PREPARING, FoodOrder.STATUS_READY}:
            allowed: dict[str, set[str]] = {
                FoodOrder.STATUS_ACCEPTED: {FoodOrder.STATUS_PENDING},
                FoodOrder.STATUS_PREPARING: {FoodOrder.STATUS_PENDING, FoodOrder.STATUS_ACCEPTED},
                FoodOrder.STATUS_READY: {FoodOrder.STATUS_ACCEPTED, FoodOrder.STATUS_PREPARING},
            }
            prev = (order.status or "").strip()
            if prev not in allowed.get(action, set()):
                messages.error(request, f"Invalid transition: {order.get_status_display()} → {action}.")
            else:
                order.status = action
                order.save(update_fields=["status", "updated_at"])
                messages.success(request, f"Order #{order.id} updated.")
        elif action == "complete":
            if (order.status or "").strip() != FoodOrder.STATUS_READY:
                messages.error(request, "Order must be in READY status to complete.")
                return redirect("food_vendor_dashboard")

            if not (order.pickup_code or "").strip():
                order.pickup_code = secrets.token_hex(3).upper()
                order.save(update_fields=["pickup_code", "updated_at"])

            code = (request.POST.get("pickup_code") or "").strip().upper()
            if not code or code != (order.pickup_code or "").strip().upper():
                messages.error(request, "Invalid pickup code.")
            else:
                order.status = FoodOrder.STATUS_COMPLETED
                order.save(update_fields=["status", "updated_at"])
                messages.success(request, f"Order #{order.id} completed.")

    return redirect("food_vendor_dashboard")


@login_required
@require_vendor
def vendor_delivered_orders(request: HttpRequest) -> HttpResponse:
    categories = MenuCategory.objects.filter(operators=request.user, stall__is_active=True).select_related("stall").order_by(
        "stall__name", "sort_order", "name"
    )
    stalls_from_categories = FoodStall.objects.filter(categories__in=categories, is_active=True)
    stalls_from_stall_ops = FoodStall.objects.filter(operators=request.user, is_active=True)
    stalls = (stalls_from_categories | stalls_from_stall_ops).distinct().order_by("name")

    orders = (
        FoodOrder.objects.select_related("stall")
        .prefetch_related("items", "items__menu_item")
        .filter(stall__in=stalls, status=FoodOrder.STATUS_COMPLETED)
        .order_by("-updated_at")
    )

    return render(
        request,
        "food_ordering/vendor_delivered_orders.html",
        {
            "stalls": stalls,
            "categories": categories,
            "orders": orders,
        },
    )


@login_required
def order_analytics(request: HttpRequest) -> HttpResponse:
    """Analytics dashboard for administrators to visualize order patterns by break slot."""
    # Restrict to staff/superuser or VENDOR group members
    user = request.user
    is_admin = getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)
    is_vendor = bool(getattr(user, "groups", None) and user.groups.filter(name="VENDOR").exists())
    if not (is_admin or is_vendor):
        messages.error(request, "Not authorized to view analytics.")
        return redirect("food_home")

    # Date range filter (default: last 7 days)
    try:
        days = int(request.GET.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days not in [7, 14, 30, 90]:
        days = 7
    since = timezone.now() - timezone.timedelta(days=days)

    # Auto-refresh (near real-time)
    try:
        autorefresh = int(request.GET.get("autorefresh", 1))
    except (TypeError, ValueError):
        autorefresh = 1
    try:
        refresh_seconds = int(request.GET.get("refresh_seconds", 10))
    except (TypeError, ValueError):
        refresh_seconds = 10
    autorefresh = 1 if autorefresh else 0
    refresh_seconds = max(5, min(refresh_seconds, 60))

    # Base queryset
    qs = FoodOrder.objects.filter(created_at__gte=since).exclude(status=FoodOrder.STATUS_CANCELLED)
    if is_vendor and not is_admin:
        # Vendors only see their assigned stalls
        categories = MenuCategory.objects.filter(operators=user).values_list("stall_id", flat=True)
        stall_ids = list(FoodStall.objects.filter(
            Q(id__in=categories) | Q(operators=user)
        ).values_list("id", flat=True))
        qs = qs.filter(stall_id__in=stall_ids)

    # Item-level queryset for safe aggregations (revenue = unit_price * qty)
    items_qs = FoodOrderItem.objects.filter(order__in=qs)
    revenue_expr = ExpressionWrapper(
        F("unit_price") * F("qty"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    # Aggregate orders by break slot
    slot_stats = (
        items_qs.exclude(order__break_slot__isnull=True)
        .values(
            "order__break_slot__label",
            "order__break_slot__start_time",
            "order__break_slot__end_time",
        )
        .annotate(
            total_orders=Count("order_id", distinct=True),
            total_items=Sum("qty"),
            total_revenue=Sum(revenue_expr),
        )
        .order_by("order__break_slot__start_time")
    )

    # Aggregate by date for trend chart
    daily_stats = (
        items_qs.annotate(date=TruncDate("order__created_at"))
        .values("date")
        .annotate(
            orders=Count("order_id", distinct=True),
            items=Sum("qty"),
        )
        .order_by("date")
    )

    # Peak hours analysis (hour of day)
    hourly_stats = (
        qs.annotate(hour=ExtractHour("created_at"))
        .values("hour")
        .annotate(orders=Count("id"))
        .order_by("hour")
    )

    # Stall-wise breakdown
    stall_stats = (
        items_qs.values("order__stall__name")
        .annotate(
            orders=Count("order_id", distinct=True),
            items=Sum("qty"),
            revenue=Sum(revenue_expr),
        )
        .order_by("-orders")
    )

    # Summary metrics
    total_orders = qs.count()
    items_summary = items_qs.aggregate(
        total_items=Sum("qty"),
        total_revenue=Sum(revenue_expr),
    )
    total_items = int(items_summary.get("total_items") or 0)
    total_revenue = items_summary.get("total_revenue") or 0
    avg_items_per_order = (total_items / total_orders) if total_orders else 0

    summary = {
        "total_orders": total_orders,
        "total_items": total_items,
        "total_revenue": total_revenue,
        "avg_items_per_order": avg_items_per_order,
    }

    context = {
        "days": days,
        "autorefresh": autorefresh,
        "refresh_seconds": refresh_seconds,
        "last_updated": timezone.now(),
        "slot_stats": list(slot_stats),
        "daily_stats": list(daily_stats),
        "hourly_stats": list(hourly_stats),
        "stall_stats": list(stall_stats),
        "summary": summary,
        "is_admin": is_admin,
    }
    return render(request, "food_ordering/analytics.html", context)
