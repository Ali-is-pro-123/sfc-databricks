from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/login/", views.SignInView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path("accounts/users/", views.account_list, name="list"),
    path("accounts/users/new/", views.account_create, name="create"),
]
