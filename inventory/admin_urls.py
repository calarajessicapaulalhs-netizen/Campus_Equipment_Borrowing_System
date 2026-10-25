from django.urls import path

from . import views

urlpatterns = [
    path("", views.admin_dashboard, name="admin_dashboard"),
    path("requests/", views.request_queue, name="request_queue"),
    path(
        "requests/<int:pk>/decision/",
        views.request_decide,
        name="request_decide",
    ),
    path(
        "requests/<int:pk>/due-date/",
        views.change_due_date,
        name="change_due_date",
    ),
    path("requests/<int:pk>/issue/", views.issue, name="issue"),
    path("loans/", views.loans, name="loans"),
    path("loans.csv", views.export_loans, name="export_loans"),
    path(
        "loans/<int:pk>/slip/",
        views.borrowing_slip,
        name="borrowing_slip",
    ),
    path("returns/", views.returns, name="returns"),
    path("returns/<int:pk>/", views.record_return, name="record_return"),
    path("inventory/", views.inventory_list, name="inventory_list"),
    path("inventory/units/new/", views.unit_create, name="unit_create"),
    path(
        "inventory/units/<int:pk>/edit/",
        views.unit_edit,
        name="unit_edit",
    ),
    path(
        "inventory/units/<int:pk>/retire/",
        views.unit_retire,
        name="unit_retire",
    ),
    path("catalog/", views.catalog, name="catalog"),
    path(
        "catalog/categories/new/",
        views.category_create,
        name="category_create",
    ),
    path(
        "catalog/categories/<int:pk>/edit/",
        views.category_edit,
        name="category_edit",
    ),
    path(
        "catalog/items/new/",
        views.item_create,
        name="item_create",
    ),
    path(
        "catalog/items/<int:pk>/edit/",
        views.item_edit,
        name="item_edit",
    ),
    path(
        "catalog/archive/<str:kind>/<int:pk>/",
        views.archive_record,
        name="archive_record",
    ),
    path("accounts/", views.accounts, name="accounts"),
    path(
        "accounts/<int:pk>/history/",
        views.account_history,
        name="account_history",
    ),
    path(
        "accounts/<int:pk>/toggle/",
        views.account_toggle,
        name="account_toggle",
    ),
    path("settings/", views.settings_view, name="settings"),
    path("audit/", views.audit_page, name="audit_page"),
    path("maintenance/", views.maintenance, name="maintenance"),
    path(
        "maintenance/<int:pk>/close/",
        views.maintenance_close,
        name="maintenance_close",
    ),
]

