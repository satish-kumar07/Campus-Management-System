from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.account_home, name="home"),
    path("profile/", views.account_home, name="profile"),
    path("profile/edit/", views.edit_profile, name="edit_profile"),
    path("password/change/", views.change_password, name="change_password"),
    path("faculty/signup/", views.faculty_signup, name="faculty_signup"),
]
