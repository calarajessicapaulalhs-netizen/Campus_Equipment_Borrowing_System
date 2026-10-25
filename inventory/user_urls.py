from django.urls import path

from . import views

urlpatterns = [
    path("", views.portal_home, name="portal_home"),
    path("profile/", views.profile, name="profile"),
    path("requests/new/", views.request_create, name="request_create"),
    path(
        "requests/<int:pk>/cancel/",
        views.request_cancel,
        name="request_cancel",
    ),
]

