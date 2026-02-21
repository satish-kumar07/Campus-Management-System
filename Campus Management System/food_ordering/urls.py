from django.urls import path

from . import views

urlpatterns = [
    path("", views.food_home, name="food_home"),
    path("stalls/", views.stalls_list, name="food_stalls_list"),
    path("stalls/<int:stall_id>/", views.stall_menu, name="food_stall_menu"),
    path("stalls/<int:stall_id>/preorder/", views.preorder, name="food_preorder"),
    path("stalls/<int:stall_id>/pickup-slot/", views.select_pickup_slot, name="food_select_pickup_slot"),
    path("stalls/<int:stall_id>/pickup-slot/confirm/", views.confirm_pickup_slot, name="food_confirm_pickup_slot"),
    path("orders/<int:order_id>/confirmation/", views.order_confirmation, name="food_order_confirmation"),
    path("orders/", views.my_orders, name="food_my_orders"),
    path("vendor/", views.vendor_dashboard, name="food_vendor_dashboard"),
    path("vendor/delivered/", views.vendor_delivered_orders, name="food_vendor_delivered_orders"),
    path("vendor/orders/<int:order_id>/update/", views.vendor_update_order, name="food_vendor_update_order"),
    path("analytics/", views.order_analytics, name="food_order_analytics"),
]
