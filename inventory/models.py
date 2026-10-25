from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        BASIC_USER = "BASIC_USER", "Basic user"
        ADMIN = "ADMIN", "Admin"

    role = models.CharField(
        max_length=12,
        choices=Role.choices,
        default=Role.BASIC_USER,
    )
    phone = models.CharField(max_length=30, blank=True)


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class CatalogItem(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="items",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["category", "name"],
                name="unique_item_per_category",
            ),
        ]

    def __str__(self):
        return self.name


class EquipmentUnit(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        RESERVED = "RESERVED", "Reserved"
        ISSUED = "ISSUED", "Issued"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        RETIRED = "RETIRED", "Retired"

    class Condition(models.TextChoices):
        EXCELLENT = "EXCELLENT", "Excellent"
        GOOD = "GOOD", "Good"
        FAIR = "FAIR", "Fair"
        DAMAGED = "DAMAGED", "Damaged"

    asset_code = models.CharField(max_length=40, unique=True)
    item = models.ForeignKey(
        CatalogItem,
        on_delete=models.PROTECT,
        related_name="units",
    )
    condition = models.CharField(
        max_length=12,
        choices=Condition.choices,
        default=Condition.GOOD,
    )
    acquired_on = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )

    def __str__(self):
        return self.asset_code


class SystemSetting(models.Model):
    max_loan_days = models.PositiveSmallIntegerField(default=7)
    max_quantity = models.PositiveSmallIntegerField(default=3)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        return cls.objects.first() or cls.objects.create()


class BorrowRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
        ISSUED = "ISSUED", "Issued"
        PARTIAL = "PARTIAL", "Partially returned"
        RETURNED = "RETURNED", "Returned"

    owner = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="borrow_requests",
    )
    purpose = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField()
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )
    decision_reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Request #{self.pk} by {self.owner}"


class RequestItem(models.Model):
    request = models.ForeignKey(
        BorrowRequest,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    item = models.ForeignKey(CatalogItem, on_delete=models.PROTECT)
    quantity = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["request", "item"],
                name="unique_catalog_per_request",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="positive_request_quantity",
            ),
        ]


class UnitAllocation(models.Model):
    request_item = models.ForeignKey(
        RequestItem,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    unit = models.ForeignKey(
        EquipmentUnit,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    allocated_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["unit"],
                condition=Q(released_at__isnull=True),
                name="one_active_allocation_per_unit",
            ),
        ]


class Loan(models.Model):
    request = models.OneToOneField(
        BorrowRequest,
        on_delete=models.PROTECT,
        related_name="loan",
    )
    issued_at = models.DateTimeField()
    issued_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="loans_issued",
    )
    due_date = models.DateField()

    @property
    def outstanding(self):
        return self.allocations.filter(return_record__isnull=True)

    @property
    def is_overdue(self):
        return self.outstanding.exists() and timezone.localdate() > self.due_date

    @property
    def overdue_days(self):
        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.due_date).days

    @property
    def allocations(self):
        return UnitAllocation.objects.filter(
            request_item__request=self.request,
        )


class ReturnRecord(models.Model):
    allocation = models.OneToOneField(
        UnitAllocation,
        on_delete=models.PROTECT,
        related_name="return_record",
    )
    returned_at = models.DateTimeField(default=timezone.now)
    condition = models.CharField(
        max_length=12,
        choices=EquipmentUnit.Condition.choices,
    )
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT)


class MaintenanceRecord(models.Model):
    unit = models.ForeignKey(
        EquipmentUnit,
        on_delete=models.PROTECT,
        related_name="maintenance_records",
    )
    problem = models.TextField()
    action = models.TextField(blank=True)
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    opened_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="maintenance_opened",
    )
    closed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="maintenance_closed",
    )

    @property
    def is_open(self):
        return self.closed_at is None


class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    reference_type = models.CharField(max_length=60)
    reference_id = models.PositiveIntegerField()
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

