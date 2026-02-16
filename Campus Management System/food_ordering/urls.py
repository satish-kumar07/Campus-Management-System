from django.urls import path

from . import views

urlpatterns = [
    path("", views.food_home, name="food_home"),
    path("stalls/", views.stalls_list, name="food_stalls_list"),
    path("stalls/<int:stall_id>/", views.stall_menu, name="food_stall_menu"),
    path("stalls/<int:stall_id>/preorder/", views.preorder, name="food_preorder"),
    path("orders/", views.my_orders, name="food_my_orders"),
]
