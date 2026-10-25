from django.urls import include, path

from inventory import views

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/login/", views.login_page, name="login"),
    path("accounts/logout/", views.logout_page, name="logout"),
    path("accounts/forgot-password/", views.forgot_password, name="forgot_password"),
    path("forgot-password/", views.forgot_password),
    path("register/", views.register, name="register"),
    path("manage/", include("inventory.admin_urls")),
    path("portal/", include("inventory.user_urls")),
]

