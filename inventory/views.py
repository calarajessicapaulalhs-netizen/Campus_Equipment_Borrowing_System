import csv
import json
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Value
from django.db.models.functions import Concat
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .access import admin_required, user_required
from .forms import (
    CatalogItemForm,
    CategoryForm,
    CloseMaintenanceForm,
    DecisionForm,
    DueDateForm,
    EquipmentUnitEditForm,
    EquipmentUnitForm,
    MaintenanceForm,
    ProfileForm,
    RegistrationForm,
    RequestForm,
    RequestLineForm,
    ReturnForm,
    SettingForm,
    SignInForm,
)
from .models import (
    AuditLog,
    BorrowRequest,
    CatalogItem,
    Category,
    EquipmentUnit,
    Loan,
    MaintenanceRecord,
    RequestItem,
    ReturnRecord,
    SystemSetting,
    UnitAllocation,
    User,
)
from .services import audit, cancel_request, decide_request, issue_request, return_unit

def home(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return redirect('admin_dashboard' if request.user.role == User.Role.ADMIN else 'portal_home')

def login_page(request):
    if request.user.is_authenticated:
        return home(request)
    form = SignInForm(request, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        return home(request)
    return render(request, 'registration/login.html', {'form': form})

def logout_page(request):
    if request.method == 'POST':
        logout(request)
    return redirect('login')

def register(request):
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        u = form.save()
        login(request, u)
        messages.success(request, 'Your account was created and you are now logged in.')
        return redirect('portal_home')
    return render(request, 'registration/register.html', {'form': form})

def forgot_password(request):
    if request.user.is_authenticated:
        return home(request)
    success = False
    error = None
    identifier = ""
    if request.method == 'POST':
        identifier = request.POST.get('username_or_email', '').strip()
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not identifier:
            error = "Please enter your username or registered email."
        elif not new_password:
            error = "Please enter your new password."
        elif len(new_password) < 8:
            error = "Password must be at least 8 characters long."
        elif new_password != confirm_password:
            error = "Confirmation password does not match the new password."
        else:
            user = User.objects.filter(Q(username=identifier) | Q(email__iexact=identifier)).first()
            if not user:
                error = f"No user account found matching '{identifier}'."
            else:
                try:
                    validate_password(new_password, user=user)
                    user.set_password(new_password)
                    user.save()
                    audit(user, "PASSWORD_RESET", user, "Password was reset via forgot password workflow.")
                    success = True
                except ValidationError as ve:
                    error = " ".join(ve.messages)

    return render(request, 'registration/forgot_password.html', {
        'success': success,
        'error': error,
        'identifier': identifier,
    })

@admin_required
def admin_dashboard(request):
    active = Loan.objects.filter(request__status__in=['ISSUED', 'PARTIAL']).select_related(
        'request__owner'
    ).prefetch_related(
        'request__lines__item'
    )
    cards = {
        "available": EquipmentUnit.objects.filter(status="AVAILABLE").count(),
        "pending": BorrowRequest.objects.filter(status="PENDING").count(),
        "active": active.count(),
        "overdue": sum(loan.is_overdue for loan in active),
    }
    today = timezone.localdate()

    # Accurate Daily Data (Last 7 Days) for working line chart
    daily_labels = []
    daily_loans = []
    daily_returns = []
    for ago in range(6, -1, -1):
        day = today - timedelta(days=ago)
        daily_labels.append(day.strftime("%b %d"))
        l_cnt = Loan.objects.filter(issued_at__date=day).count()
        r_cnt = ReturnRecord.objects.filter(returned_at__date=day).count()
        daily_loans.append(l_cnt)
        daily_returns.append(r_cnt)

    # Accurate Monthly Data (Last 6 Months) for working line chart
    monthly_labels = []
    monthly_loans = []
    monthly_returns = []
    for ago in range(5, -1, -1):
        month = (today.replace(day=1) - timedelta(days=ago * 30)).replace(day=1)
        monthly_labels.append(month.strftime("%b %Y"))
        l_cnt = Loan.objects.filter(
            issued_at__year=month.year,
            issued_at__month=month.month,
        ).count()
        r_cnt = ReturnRecord.objects.filter(
            returned_at__year=month.year,
            returned_at__month=month.month,
        ).count()
        monthly_loans.append(l_cnt)
        monthly_returns.append(r_cnt)

    chart_daily_json = json.dumps({
        "labels": daily_labels,
        "loans": daily_loans,
        "returns": daily_returns,
    })
    chart_monthly_json = json.dumps({
        "labels": monthly_labels,
        "loans": monthly_loans,
        "returns": monthly_returns,
    })

    # Status filter for Records table
    status_filter = request.GET.get('status', '').strip().upper()
    recent_qs = BorrowRequest.objects.select_related(
        'owner', 'loan'
    ).prefetch_related(
        'lines__item'
    ).order_by('-submitted_at')

    if status_filter == 'OVERDUE':
        recent_qs = recent_qs.filter(
            status__in=['ISSUED', 'PARTIAL'],
            loan__due_date__lt=today,
        )
    elif status_filter in ['PENDING', 'APPROVED', 'REJECTED', 'CANCELLED', 'ISSUED', 'PARTIAL', 'RETURNED']:
        recent_qs = recent_qs.filter(status=status_filter)

    recent_records = list(recent_qs[:7])
    active_loans = list(active.order_by('-issued_at')[:25])

    seven_days_ago = timezone.now() - timedelta(days=7)
    loans_last_7_days = Loan.objects.filter(issued_at__gte=seven_days_ago).count()

    categories = Category.objects.annotate(
        usage=Count("items__requestitem__request__loan", distinct=True),
        total_units=Count("items__units", distinct=True),
    ).order_by("name")

    category_chart_json = json.dumps({
        "labels": [c.name for c in categories],
        "usage": [c.usage for c in categories],
        "units": [c.total_units for c in categories],
    })

    return render(
        request,
        "manage/dashboard.html",
        {
            "cards": cards,
            "categories": categories,
            "recent_records": recent_records,
            "active_loans": active_loans,
            "loans_last_7_days": loans_last_7_days,
            "status_filter": status_filter,
            "chart_daily_json": chart_daily_json,
            "chart_monthly_json": chart_monthly_json,
            "category_chart_json": category_chart_json,
        },
    )

@admin_required
def request_queue(request):
    qs = BorrowRequest.objects.select_related('owner').prefetch_related('lines__item').order_by('-submitted_at')
    status = request.GET.get('status', '').strip()
    q = request.GET.get('q', '').strip()
    date_preset = request.GET.get('date_preset', '').strip()
    start = request.GET.get('start', '').strip()
    end = request.GET.get('end', '').strip()

    today = timezone.localdate()
    if date_preset == 'today':
        start = today.isoformat()
        end = today.isoformat()
    elif date_preset == 'yesterday':
        yesterday = today - timedelta(days=1)
        start = yesterday.isoformat()
        end = yesterday.isoformat()
    elif date_preset == 'week':
        start = (today - timedelta(days=7)).isoformat()
        end = today.isoformat()
    elif date_preset == 'month':
        start = today.replace(day=1).isoformat()
        end = today.isoformat()

    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.annotate(owner_full_name=Concat('owner__first_name', Value(' '), 'owner__last_name')).filter(Q(owner__username__icontains=q) | Q(owner__first_name__icontains=q) | Q(owner__last_name__icontains=q) | Q(owner_full_name__icontains=q) | Q(purpose__icontains=q))
    if start:
        qs = qs.filter(submitted_at__date__gte=start)
    if end:
        qs = qs.filter(submitted_at__date__lte=end)
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    requests = list(page.object_list)
    lines = [line for obj in requests for line in obj.lines.all()]
    item_ids = {line.item_id for line in lines}
    available_by_item = dict(
        EquipmentUnit.objects.filter(
            item_id__in=item_ids,
            status=EquipmentUnit.Status.AVAILABLE,
        )
        .values_list("item_id")
        .annotate(available=Count("pk"))
    )
    for line in lines:
        line.available_quantity = available_by_item.get(line.item_id, 0)
    for obj in requests:
        obj.can_approve = all(
            line.available_quantity >= line.quantity
            for line in obj.lines.all()
        )
    page.object_list = requests
    context = {
        "page": page,
        "statuses": BorrowRequest.Status.choices,
        "status": status,
        "q": q,
        "start": start,
        "end": end,
        "date_preset": date_preset,
    }
    return render(request, "manage/requests.html", context)

@admin_required
def request_decide(request, pk):
    obj = get_object_or_404(BorrowRequest.objects.prefetch_related('lines__item'), pk=pk)
    available_by_item = dict(
        EquipmentUnit.objects.filter(
            item_id__in=obj.lines.values_list("item_id", flat=True),
            status=EquipmentUnit.Status.AVAILABLE,
        )
        .values_list("item_id")
        .annotate(available=Count("pk"))
    )
    for line in obj.lines.all():
        line.available_quantity = available_by_item.get(line.item_id, 0)
    obj.can_approve = all(
        line.available_quantity >= line.quantity
        for line in obj.lines.all()
    )
    form = DecisionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            decide_request(obj, request.user, form.cleaned_data['decision'] == 'approve', form.cleaned_data['reason'])
            messages.success(request, 'Decision recorded.')
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        except IntegrityError:
            messages.error(
                request,
                'A unit was allocated before this decision could be saved. '
                'Refresh the request queue and review availability again.',
            )
        return redirect('request_queue')
    return render(
        request,
        "shared/form.html",
        {
            "form": form,
            "title": f"Review request #{obj.pk}",
            "object": obj,
            "back": "request_queue",
        },
    )

@admin_required
def issue(request, pk):
    if request.method == 'POST':
        try:
            issue_request(get_object_or_404(BorrowRequest, pk=pk), request.user)
            messages.success(request, 'Loan issued.')
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
    return redirect('request_queue')

@admin_required
def change_due_date(request, pk):
    obj = get_object_or_404(BorrowRequest, pk=pk, status='APPROVED')
    form = DueDateForm(request.POST or None, initial={'due_date': obj.due_date})
    if request.method == 'POST' and form.is_valid():
        old = obj.due_date
        obj.due_date = form.cleaned_data['due_date']
        obj.save(update_fields=['due_date'])
        audit(request.user, 'DUE_DATE_CHANGE', obj, f"{old} -> {obj.due_date}: {form.cleaned_data['reason']}")
        messages.success(request, 'Due date updated and logged.')
        return redirect('request_queue')
    return render(
        request,
        "shared/form.html",
        {
            "form": form,
            "title": "Revise agreed due date",
            "back": "request_queue",
        },
    )

@admin_required
def loans(request):
    qs = Loan.objects.select_related('request__owner').prefetch_related('request__lines__allocations__unit').order_by('-issued_at')
    start = request.GET.get('start')
    end = request.GET.get('end')
    overdue_only = request.GET.get('overdue') == '1'
    if start:
        qs = qs.filter(issued_at__date__gte=start)
    if end:
        qs = qs.filter(issued_at__date__lte=end)
    rows = [(l, l.is_overdue, l.overdue_days) for l in qs]
    if overdue_only:
        rows = [r for r in rows if r[1]]
    matching_loans = [r[0] for r in rows]
    total_loans = len(rows)
    overdue_loans = sum(1 for r in rows if r[1])
    active_loans = sum(1 for loan, overdue, _days in rows if loan.request.status in (BorrowRequest.Status.ISSUED, BorrowRequest.Status.PARTIAL) and not overdue)
    total_overdue_days = sum(r[2] for r in rows)
    total_units = UnitAllocation.objects.filter(request_item__request__loan__in=matching_loans).count()
    summary = {
        "total_loans": total_loans,
        "active_loans": active_loans,
        "overdue_loans": overdue_loans,
        "total_overdue_days": total_overdue_days,
        "total_units": total_units,
    }
    page = Paginator(rows, 10).get_page(request.GET.get("page"))
    return render(
        request,
        "manage/loans.html",
        {
            "rows": page,
            "page": page,
            "start": start or "",
            "end": end or "",
            "overdue_only": overdue_only,
            "summary": summary,
        },
    )

@admin_required
def borrowing_slip(request, pk):
    loan = get_object_or_404(Loan.objects.select_related('request__owner'), pk=pk)
    return render(request, 'manage/slip.html', {'loan': loan})

@admin_required
def export_loans(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="loan-report.csv"'
    w = csv.writer(response)
    w.writerow(['Loan', 'Borrower', 'Issued', 'Due', 'Status', 'Overdue days', 'Assets'])
    qs = Loan.objects.select_related('request__owner').prefetch_related('request__lines__allocations__unit')
    start = request.GET.get('start')
    end = request.GET.get('end')
    overdue_only = request.GET.get('overdue') == '1'
    if start:
        qs = qs.filter(issued_at__date__gte=start)
    if end:
        qs = qs.filter(issued_at__date__lte=end)
    for l in qs:
        if overdue_only and (not l.is_overdue):
            continue
        asset_codes = ", ".join(
            l.allocations.values_list("unit__asset_code", flat=True)
        )
        w.writerow(
            [
                l.pk,
                l.request.owner.username,
                l.issued_at.isoformat(),
                l.due_date,
                l.request.status,
                l.overdue_days,
                asset_codes,
            ]
        )
    return response

@admin_required
def inventory_list(request):
    qs = EquipmentUnit.objects.select_related('item__category').order_by('asset_code')
    status = request.GET.get('status', '')
    category = request.GET.get('category', '')
    item = request.GET.get('item', '')
    q = request.GET.get('q', '')
    if status:
        qs = qs.filter(status=status)
    if category.isdigit():
        qs = qs.filter(item__category_id=int(category))
    else:
        category = ''
    if item.isdigit():
        qs = qs.filter(item_id=int(item))
    else:
        item = ''
    if q:
        qs = qs.filter(Q(asset_code__icontains=q) | Q(item__name__icontains=q) | Q(item__category__name__icontains=q))
    totals = {v: EquipmentUnit.objects.filter(status=v).count() for v, _ in EquipmentUnit.Status.choices}
    items_qs = CatalogItem.objects.select_related("category").order_by(
        "category__name",
        "name",
    )
    if category.isdigit():
        items_qs = items_qs.filter(category_id=int(category))

    units_page = Paginator(qs, 10).get_page(request.GET.get("page"))
    context = {
        "units": units_page,
        "page": units_page,
        "statuses": EquipmentUnit.Status.choices,
        "status": status,
        "categories": Category.objects.all().order_by("name"),
        "category": category,
        "items": items_qs,
        "item": item,
        "q": q,
        "totals": totals,
    }
    return render(request, "manage/inventory.html", context)

@admin_required
def catalog(request):
    categories_qs = Category.objects.all().order_by("name")
    items_qs = CatalogItem.objects.select_related("category").order_by("category__name", "name")

    view_type = request.GET.get("view", "all").strip().lower()
    category_id = request.GET.get("category", "").strip()
    status_filter = request.GET.get("status", "").strip().upper()
    q = request.GET.get("q", "").strip()

    all_categories = list(categories_qs)

    if status_filter == "ACTIVE":
        categories_qs = categories_qs.filter(is_active=True)
    elif status_filter == "ARCHIVED":
        categories_qs = categories_qs.filter(is_active=False)

    if q:
        categories_qs = categories_qs.filter(name__icontains=q)

    if category_id.isdigit():
        items_qs = items_qs.filter(category_id=int(category_id))
        if view_type == "all":
            view_type = "items"

    if status_filter == "ACTIVE":
        items_qs = items_qs.filter(is_active=True)
    elif status_filter == "ARCHIVED":
        items_qs = items_qs.filter(is_active=False)

    if q:
        items_qs = items_qs.filter(Q(name__icontains=q) | Q(category__name__icontains=q))

    categories_page = Paginator(categories_qs, 10).get_page(request.GET.get("cat_page"))
    items_page = Paginator(items_qs, 10).get_page(request.GET.get("page"))

    context = {
        "all_categories": all_categories,
        "categories": categories_page,
        "cat_page": categories_page,
        "items": items_page,
        "page": items_page,
        "view_type": view_type,
        "category_id": category_id,
        "status_filter": status_filter,
        "q": q,
    }
    return render(request, "manage/catalog.html", context)

@admin_required
def category_create(request):
    form = CategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        audit(request.user, 'CATEGORY_CREATE', obj)
        return redirect('catalog')
    return render(request, 'shared/form.html', {'form': form, 'title': 'Add category', 'back': 'catalog'})

@admin_required
def category_edit(request, pk):
    obj = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit(request.user, 'CATEGORY_UPDATE', obj)
        return redirect('catalog')
    return render(request, 'shared/form.html', {'form': form, 'title': 'Edit category', 'back': 'catalog'})

@admin_required
def item_create(request):
    form = CatalogItemForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        audit(request.user, 'ITEM_CREATE', obj)
        return redirect('catalog')
    return render(request, 'shared/form.html', {'form': form, 'title': 'Add catalog item', 'back': 'catalog'})

@admin_required
def item_edit(request, pk):
    obj = get_object_or_404(CatalogItem, pk=pk)
    form = CatalogItemForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit(request.user, 'ITEM_UPDATE', obj)
        return redirect('catalog')
    return render(request, 'shared/form.html', {'form': form, 'title': 'Edit catalog item', 'back': 'catalog'})

@admin_required
def unit_create(request):
    form = EquipmentUnitForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        quantity = form.cleaned_data["quantity"]
        base_code = form.cleaned_data["asset_code"].strip()
        codes = (
            [base_code]
            if quantity == 1
            else [f"{base_code}-{number:03d}" for number in range(1, quantity + 1)]
        )
        existing_codes = set(
            EquipmentUnit.objects.filter(asset_code__in=codes)
            .values_list("asset_code", flat=True)
        )
        if existing_codes:
            form.add_error(
                "asset_code",
                "These asset codes already exist: " + ", ".join(sorted(existing_codes)),
            )
        else:
            condition = form.cleaned_data["condition"]
            initial_status = (
                EquipmentUnit.Status.MAINTENANCE
                if condition == EquipmentUnit.Condition.DAMAGED
                else EquipmentUnit.Status.AVAILABLE
            )
            with transaction.atomic():
                units = [
                    EquipmentUnit(
                        asset_code=code,
                        item=form.cleaned_data["item"],
                        condition=condition,
                        acquired_on=form.cleaned_data["acquired_on"],
                        status=initial_status,
                    )
                    for code in codes
                ]
                EquipmentUnit.objects.bulk_create(units)
                created_units = EquipmentUnit.objects.filter(asset_code__in=codes)
                for unit in created_units:
                    audit(request.user, "UNIT_CREATE", unit)
                    if condition == EquipmentUnit.Condition.DAMAGED:
                        maintenance = MaintenanceRecord.objects.create(
                            unit=unit,
                            problem="Unit registered as damaged; inspection required.",
                            opened_by=request.user,
                        )
                        audit(request.user, "MAINTENANCE_OPEN", maintenance)
            messages.success(
                request,
                (
                    f"Registered {quantity} physical unit(s) in maintenance."
                    if condition == EquipmentUnit.Condition.DAMAGED
                    else f"Registered {quantity} available physical unit(s)."
                ),
            )
            return redirect('inventory_list')
    return render(
        request,
        "shared/form.html",
        {"form": form, "title": "Register physical unit", "back": "inventory_list"},
    )

@admin_required
def unit_edit(request, pk):
    obj = get_object_or_404(EquipmentUnit, pk=pk)
    if obj.status in [EquipmentUnit.Status.RESERVED, EquipmentUnit.Status.ISSUED]:
        messages.error(request, 'Reserved or issued unit details cannot be edited.')
        return redirect('inventory_list')
    form = EquipmentUnitEditForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            if (
                obj.condition == EquipmentUnit.Condition.DAMAGED
                and obj.status != EquipmentUnit.Status.RETIRED
            ):
                obj.status = EquipmentUnit.Status.MAINTENANCE
                obj.save(update_fields=['status'])
                has_open_maintenance = obj.maintenance_records.filter(
                    closed_at__isnull=True,
                ).exists()
                if not has_open_maintenance:
                    maintenance = MaintenanceRecord.objects.create(
                        unit=obj,
                        problem="Unit condition changed to damaged; inspection required.",
                        opened_by=request.user,
                    )
                    audit(request.user, 'MAINTENANCE_OPEN', maintenance)
            audit(request.user, 'UNIT_UPDATE', obj)
        messages.success(
            request,
            'Unit updated. Damaged units are now in maintenance.',
        )
        return redirect('inventory_list')
    return render(request, 'shared/form.html', {'form': form, 'title': 'Edit physical unit', 'back': 'inventory_list'})

@admin_required
def unit_retire(request, pk):
    obj = get_object_or_404(EquipmentUnit, pk=pk)
    if request.method == 'POST':
        if obj.status not in ['AVAILABLE', 'MAINTENANCE']:
            messages.error(request, 'Only an available or maintained unit can be retired.')
        else:
            with transaction.atomic():
                obj.status = 'RETIRED'
                obj.save(update_fields=['status'])
                # Automatically close any open maintenance records for this unit
                open_maintenances = obj.maintenance_records.filter(closed_at__isnull=True)
                for m in open_maintenances:
                    m.closed_at = timezone.now()
                    m.closed_by = request.user
                    m.action = "Unit retired from inventory"
                    m.save(update_fields=['closed_at', 'closed_by', 'action'])
                    audit(request.user, 'MAINTENANCE_CLOSE', m, 'Closed due to unit retirement')
                audit(request.user, 'UNIT_RETIRE', obj)
            messages.success(request, 'Unit retired.')
    return redirect('inventory_list')

@admin_required
def archive_record(request, kind, pk):
    if request.method == 'POST':
        model = {'category': Category, 'item': CatalogItem}.get(kind)
        obj = get_object_or_404(model, pk=pk)
        obj.is_active = False
        obj.save(update_fields=['is_active'])
        audit(request.user, f'{kind.upper()}_ARCHIVE', obj)
        messages.success(request, 'Record archived.')
    return redirect('catalog')

@admin_required
def returns(request):
    qs = (
        UnitAllocation.objects.filter(
            request_item__request__status__in=["ISSUED", "PARTIAL"],
            released_at__isnull=True,
            return_record__isnull=True,
        )
        .select_related("unit", "request_item__request__owner")
        .order_by("pk")
    )
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    recent_returns = ReturnRecord.objects.select_related('allocation__unit', 'allocation__request_item__request__owner', 'recorded_by').order_by('-returned_at')[:25]
    return render(request, 'manage/returns.html', {'allocations': page, 'page': page, 'recent_returns': recent_returns})

@admin_required
def record_return(request, pk):
    a = get_object_or_404(UnitAllocation, pk=pk)
    form = ReturnForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            return_unit(a, request.user, form.cleaned_data['condition'], form.cleaned_data['return_date'])
            messages.success(request, 'Return recorded.')
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        return redirect('returns')
    return render(
        request,
        "shared/form.html",
        {
            "form": form,
            "title": f"Record return for {a.unit.asset_code}",
            "back": "returns",
            "confirmation": "Record this unit return? This updates the loan and unit status.",
        },
    )

@admin_required
def accounts(request):
    qs = User.objects.filter(role='BASIC_USER').order_by('last_name')
    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    page = Paginator(qs, 10).get_page(request.GET.get('page'))
    return render(request, 'manage/accounts.html', {'users': page, 'page': page, 'q': q})

@admin_required
def account_history(request, pk):
    account = get_object_or_404(User, pk=pk, role='BASIC_USER')
    requests = BorrowRequest.objects.filter(owner=account).prefetch_related('lines__item').order_by('-submitted_at')
    page = Paginator(requests, 10).get_page(request.GET.get('page'))
    return render(request, 'manage/account_history.html', {'account': account, 'requests': page, 'page': page})

@admin_required
def account_toggle(request, pk):
    u = get_object_or_404(User, pk=pk, role='BASIC_USER')
    if request.method == 'POST':
        u.is_active = not u.is_active
        u.save(update_fields=['is_active'])
        audit(request.user, 'ACCOUNT_STATUS', u)
        messages.success(request, 'Account updated.')
    return redirect('accounts')

@admin_required
def settings_view(request):
    obj = SystemSetting.current()
    form = SettingForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit(request.user, 'SETTINGS_UPDATE', obj)
        messages.success(request, 'Settings saved.')
        return redirect('settings')
    return render(
        request,
        "shared/form.html",
        {"form": form, "title": "Operational settings", "back": "admin_dashboard"},
    )

@admin_required
def audit_page(request):
    qs = AuditLog.objects.select_related('actor').order_by('-created_at')
    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(
            Q(action__icontains=q)
            | Q(reference_type__icontains=q)
            | Q(detail__icontains=q)
            | Q(actor__username__icontains=q)
        )
    page = Paginator(qs, 10).get_page(request.GET.get('page'))
    return render(request, 'manage/audit.html', {'logs': page, 'page': page, 'q': q})

@admin_required
def maintenance(request):
    form = MaintenanceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        unit = form.cleaned_data['unit']
        has_open_record = unit.maintenance_records.filter(
            closed_at__isnull=True,
        ).exists()
        if unit.status not in ["AVAILABLE", "MAINTENANCE"] or has_open_record:
            messages.error(request, 'Issued, reserved, or already-maintained units cannot enter maintenance.')
        else:
            obj = form.save(commit=False)
            obj.opened_by = request.user
            obj.save()
            unit.status = 'MAINTENANCE'
            unit.save(update_fields=['status'])
            audit(request.user, 'MAINTENANCE_OPEN', obj)
            messages.success(request, 'Maintenance opened.')
            return redirect('maintenance')
    records = MaintenanceRecord.objects.select_related("unit__item", "opened_by", "closed_by").order_by("-opened_at")
    page = Paginator(records, 10).get_page(request.GET.get('page'))
    return render(
        request,
        "manage/maintenance.html",
        {"form": form, "records": page, "page": page},
    )

@admin_required
def maintenance_close(request, pk):
    obj = get_object_or_404(
        MaintenanceRecord.objects.select_related("unit__item__category", "opened_by"),
        pk=pk,
        closed_at__isnull=True,
    )
    form = CloseMaintenanceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        outcome = form.cleaned_data.get('outcome') or 'AVAILABLE'
        obj.action = form.cleaned_data['action']
        obj.closed_at = timezone.now()
        obj.closed_by = request.user
        obj.save()
        if outcome == EquipmentUnit.Status.RETIRED:
            obj.unit.status = EquipmentUnit.Status.RETIRED
            messages.success(
                request,
                f"Maintenance closed: Unit {obj.unit.asset_code} has been retired because it cannot be repaired and will stay unavailable.",
            )
        else:
            obj.unit.status = EquipmentUnit.Status.AVAILABLE
            messages.success(
                request,
                f"Maintenance closed: Unit {obj.unit.asset_code} is fixed and now available for borrowing.",
            )
        obj.unit.save(update_fields=['status'])
        audit(request.user, 'MAINTENANCE_CLOSE', obj)
        return redirect('maintenance')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('modal') == '1'
    template_name = 'manage/maintenance_close_modal.html' if is_ajax else 'manage/maintenance_close.html'
    return render(
        request,
        template_name,
        {
            'form': form,
            'record': obj,
            'title': f'Close Maintenance — {obj.unit.asset_code}',
            'back': 'maintenance',
        },
    )

@user_required
def portal_home(request):
    items = (
        CatalogItem.objects.filter(is_active=True, category__is_active=True)
        .annotate(
            available=Count(
                "units",
                filter=Q(units__status=EquipmentUnit.Status.AVAILABLE),
            ),
            serviceable=Count(
                "units",
                filter=~Q(
                    units__status__in=[
                        EquipmentUnit.Status.MAINTENANCE,
                        EquipmentUnit.Status.RETIRED,
                    ]
                ),
            ),
        )
    )
    categories = list(Category.objects.filter(is_active=True).order_by("name"))
    q = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '').strip()
    if q:
        items = items.filter(
            Q(name__icontains=q)
            | Q(category__name__icontains=q)
            | Q(description__icontains=q)
        )
    if category_id and category_id.isdecimal():
        items = items.filter(category_id=int(category_id))

    items = list(items)
    for item in items:
        name = item.name.casefold()
        if "laptop" in name:
            item.photo_path = "images/laptop.jpg"
        elif "camera" in name:
            item.photo_path = "images/camera.jpg"
        elif "projector" in name:
            item.photo_path = "images/projector.jpg"
        elif "jbl" in name:
            item.photo_path = "images/jbl.jpg"
        elif "extension" in name or "cord" in name:
            item.photo_path = "images/extension-cord.jpg"
        else:
            item.photo_path = "images/campus-background.jpg"

    user_requests = BorrowRequest.objects.filter(owner=request.user).select_related(
        "loan"
    ).prefetch_related(
        "lines__item",
        "lines__allocations__unit",
        "lines__allocations__return_record",
    ).order_by("-submitted_at")

    req_page = Paginator(user_requests, 10).get_page(request.GET.get("page"))

    stats = {
        "active": user_requests.filter(status__in=["ISSUED", "PARTIAL"]).count(),
        "pending": user_requests.filter(status="PENDING").count(),
        "approved": user_requests.filter(status="APPROVED").count(),
        "total": user_requests.count(),
    }

    return render(
        request,
        "portal/home.html",
        {
            "requests": req_page,
            "page": req_page,
            "items": items,
            "categories": categories,
            "selected_category": int(category_id) if category_id.isdecimal() else None,
            "q": q,
            "stats": stats,
        },
    )

@user_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profile updated.')
        return redirect('profile')
    return render(request, 'portal/profile.html', {'form': form})

@user_required
def request_create(request):
    form = RequestForm(request.POST or None)
    preselected_item = None
    item_id = request.GET.get("item", "")
    if request.method == "GET" and item_id.isdecimal():
        item_candidate = CatalogItem.objects.filter(
            pk=int(item_id),
            is_active=True,
            category__is_active=True,
        ).first()
        if item_candidate:
            avail = item_candidate.units.filter(status=EquipmentUnit.Status.AVAILABLE).count()
            if avail > 0:
                preselected_item = item_candidate
            else:
                messages.error(
                    request,
                    f"{item_candidate.name} is currently out of stock / unavailable and cannot be requested.",
                )

    line_initials = [
        {"item": preselected_item.pk, "quantity": 1}
        if preselected_item
        else {},
        {},
        {},
    ]
    lines = [
        RequestLineForm(
            request.POST or None,
            prefix=f"line{index}",
            initial=line_initials[index],
        )
        for index in range(3)
    ]
    # The first item slot is required; additional slots are optional.
    lines[0].fields["item"].required = True
    lines[0].fields["quantity"].required = True

    if request.method == "POST":
        request_valid = form.is_valid()
        lines_valid = [line.is_valid() for line in lines]

        if request_valid and all(lines_valid):
            selected = []
            seen_item_ids = set()
            max_quantity = SystemSetting.current().max_quantity

            for line in lines:
                item = line.cleaned_data.get("item")
                if not item:
                    continue

                quantity = line.cleaned_data.get("quantity")
                selected.append((line, item, quantity))

                if item.pk in seen_item_ids:
                    line.add_error("item", "Choose each catalog item only once.")
                else:
                    seen_item_ids.add(item.pk)

                if not quantity:
                    line.add_error("quantity", "Enter a quantity for this item.")
                elif quantity > max_quantity:
                    line.add_error(
                        "quantity",
                        f"The maximum allowed is {max_quantity} unit(s) per item.",
                    )
                else:
                    available = item.units.filter(status=EquipmentUnit.Status.AVAILABLE).count()
                    if available <= 0:
                        line.add_error("item", f"{item.name} is currently unavailable.")
                    elif quantity > available:
                        line.add_error(
                            "quantity",
                            f"Only {available} unit(s) of {item.name} are currently available.",
                        )

            if not selected:
                lines[0].add_error("item", "Select at least one equipment item.")

            if not any(line.errors for line in lines):
                with transaction.atomic():
                    obj = form.save(commit=False)
                    obj.owner = request.user
                    obj.save()
                    for _, item, quantity in selected:
                        RequestItem.objects.create(request=obj, item=item, quantity=quantity)
                messages.success(request, "Request submitted for review.")
                return redirect("portal_home")
    return render(
        request,
        "portal/request_form.html",
        {"form": form, "lines": lines, "settings": SystemSetting.current()},
    )

@user_required
def request_cancel(request, pk):
    if request.method == 'POST':
        try:
            cancel_request(get_object_or_404(BorrowRequest, pk=pk, owner=request.user), request.user)
            messages.success(request, 'Request cancelled.')
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
    return redirect('portal_home')
