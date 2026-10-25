from datetime import timedelta
from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventory.models import (
    BorrowRequest,
    CatalogItem,
    Category,
    EquipmentUnit,
    Loan,
    MaintenanceRecord,
    RequestItem,
    SystemSetting,
    UnitAllocation,
    User,
)
from inventory.services import return_unit


class Command(BaseCommand):
    help = "Create a repeatable fictional CEBIS demonstration dataset."

    def handle(self, *args, **options):
        if BorrowRequest.objects.filter(purpose__startswith="DEMO:").exists():
            self.stdout.write("Demo dataset already exists; no changes made.")
            return

        if not User.objects.filter(role=User.Role.ADMIN, is_active=True).exists():
            raise CommandError("Create an administrator first with create_admin.")

        borrower_password = getpass("Shared password for fictional demo borrowers: ")
        if len(borrower_password) < 10:
            raise CommandError("Use passwords with at least 10 characters.")

        today = timezone.localdate()
        now = timezone.now()

        with transaction.atomic():
            admin = User.objects.filter(
                role=User.Role.ADMIN,
                is_active=True,
            ).order_by("pk").first()

            borrowers = []
            for number in range(1, 9):
                user, _ = User.objects.get_or_create(
                    username=f"demo_borrower{number:02}",
                    defaults={
                        "first_name": "Demo",
                        "last_name": f"User {number:02}",
                        "email": f"demo.borrower{number:02}@example.invalid",
                        "role": User.Role.BASIC_USER,
                    },
                )
                user.first_name = "Demo"
                user.last_name = f"User {number:02}"
                user.email = f"demo.borrower{number:02}@example.invalid"
                user.role = User.Role.BASIC_USER
                user.is_active = True
                user.set_password(borrower_password)
                user.save()
                borrowers.append(user)

            category_specs = [
                ("Demo Computing", ["Demo Laptop", "Demo Projector"]),
                ("Demo Audio Visual", ["Demo Camera", "Demo Microphone"]),
                ("Demo Facilities", ["Demo Speaker", "Demo Extension Cord"]),
            ]
            items = []
            for category_name, names in category_specs:
                category, _ = Category.objects.get_or_create(
                    name=category_name,
                    defaults={"description": "Fictional demonstration category."},
                )
                category.is_active = True
                category.save(update_fields=["is_active"])
                for name in names:
                    item, _ = CatalogItem.objects.get_or_create(
                        category=category,
                        name=name,
                        defaults={
                            "description": "Fictional equipment for demonstration.",
                            "is_active": True,
                        },
                    )
                    item.is_active = True
                    item.save(update_fields=["is_active"])
                    items.append(item)

            units_by_item = {}
            for item in items:
                code_prefix = item.name.removeprefix("Demo ").replace(" ", "-").upper()
                units_by_item[item.pk] = []
                for number in range(1, 4):
                    unit, _ = EquipmentUnit.objects.get_or_create(
                        asset_code=f"DEMO-{code_prefix}-{number:02}",
                        defaults={
                            "item": item,
                            "condition": EquipmentUnit.Condition.GOOD,
                            "acquired_on": today - timedelta(days=180 + number),
                            "status": EquipmentUnit.Status.AVAILABLE,
                        },
                    )
                    unit.item = item
                    unit.condition = EquipmentUnit.Condition.GOOD
                    unit.status = EquipmentUnit.Status.AVAILABLE
                    unit.save()
                    units_by_item[item.pk].append(unit)

            settings = SystemSetting.current()
            settings.max_loan_days = 7
            settings.max_quantity = 3
            settings.save()

            # Twenty fictional requests cover pending and every required workflow branch.
            request_specs = [
                ("PENDING", 0, 1, 2, 5),
                ("PENDING", 1, 1, 2, 6),
                ("PENDING", 2, 1, 1, 4),
                ("PENDING", 3, 1, 1, 3),
                ("APPROVED", 2, 1, 2, 5),
                ("REJECTED", 5, 1, 3, 4),
                ("CANCELLED", 0, 1, 2, 4),
                ("ISSUED_OVERDUE", 0, 1, 10, -3),
                ("ISSUED_OVERDUE", 1, 1, 12, -5),
                ("ISSUED", 2, 1, 3, 3),
                ("ISSUED", 3, 1, 4, 4),
                ("PARTIAL_DAMAGED", 4, 2, 5, 3),
                ("ISSUED", 5, 1, 2, 5),
                ("ISSUED", 0, 1, 3, 4),
                ("RETURNED", 1, 1, 8, -2),
                ("RETURNED", 2, 1, 14, -8),
                ("RETURNED", 3, 1, 45, -40),
                ("RETURNED", 4, 1, 75, -70),
                ("RETURNED", 5, 1, 110, -105),
                ("RETURNED", 0, 1, 7, -2),
            ]

            for index, (kind, item_index, quantity, issued_days_ago, due_offset) in enumerate(request_specs):
                item = items[item_index]
                borrower = borrowers[index % len(borrowers)]
                due_date = today + timedelta(days=due_offset)
                request = BorrowRequest.objects.create(
                    owner=borrower,
                    purpose=f"DEMO: Fictional campus activity {index + 1:02}",
                    due_date=due_date,
                    status=BorrowRequest.Status.PENDING,
                )
                RequestItem.objects.create(
                    request=request,
                    item=item,
                    quantity=quantity,
                )
                submitted = now - timedelta(days=max(issued_days_ago, 1) + 1)
                BorrowRequest.objects.filter(pk=request.pk).update(submitted_at=submitted)

                if kind == "PENDING":
                    continue
                if kind in {"REJECTED", "CANCELLED"}:
                    request.status = (
                        BorrowRequest.Status.REJECTED
                        if kind == "REJECTED"
                        else BorrowRequest.Status.CANCELLED
                    )
                    request.decided_by = admin
                    request.decided_at = submitted
                    request.decision_reason = (
                        "DEMO: Request does not meet the fictional campus borrowing rules."
                        if kind == "REJECTED"
                        else "DEMO: Cancelled before issue."
                    )
                    request.save()
                    continue

                chosen_units = [
                    unit
                    for unit in units_by_item[item.pk]
                    if unit.status == EquipmentUnit.Status.AVAILABLE
                ][:quantity]
                if len(chosen_units) != quantity:
                    raise CommandError(f"Not enough demo units for {item.name}.")

                for unit in chosen_units:
                    UnitAllocation.objects.create(
                        request_item=request.lines.get(),
                        unit=unit,
                    )

                if kind == "APPROVED":
                    request.status = BorrowRequest.Status.APPROVED
                    request.decided_by = admin
                    request.decided_at = now
                    request.decision_reason = "DEMO: Approved and units reserved."
                    request.save()
                    for unit in chosen_units:
                        unit.status = EquipmentUnit.Status.RESERVED
                        unit.save(update_fields=["status"])
                    continue

                request.status = (
                    BorrowRequest.Status.PARTIAL
                    if kind == "PARTIAL_DAMAGED"
                    else BorrowRequest.Status.ISSUED
                )
                if kind == "RETURNED":
                    request.status = BorrowRequest.Status.ISSUED
                request.save(update_fields=["status"])
                for unit in chosen_units:
                    unit.status = EquipmentUnit.Status.ISSUED
                    unit.save(update_fields=["status"])
                loan = Loan.objects.create(
                    request=request,
                    issued_at=now - timedelta(days=issued_days_ago),
                    issued_by=admin,
                    due_date=due_date,
                )

                if kind == "PARTIAL_DAMAGED":
                    return_unit(
                        loan.allocations.order_by("pk").first(),
                        admin,
                        EquipmentUnit.Condition.DAMAGED,
                        return_date=today - timedelta(days=1),
                    )
                elif kind == "RETURNED":
                    return_unit(
                        loan.allocations.first(),
                        admin,
                        EquipmentUnit.Condition.GOOD,
                        return_date=today + timedelta(days=due_offset),
                    )

            # One damaged partial return above plus three separate maintenance units.
            maintenance_units = list(
                EquipmentUnit.objects.filter(
                    item__in=items,
                    status=EquipmentUnit.Status.AVAILABLE,
                ).order_by("asset_code")[:3]
            )
            for unit in maintenance_units:
                MaintenanceRecord.objects.create(
                    unit=unit,
                    problem="DEMO: Routine fictional equipment inspection.",
                    opened_by=admin,
                )
                unit.status = EquipmentUnit.Status.MAINTENANCE
                unit.save(update_fields=["status"])

        self.stdout.write(
            self.style.SUCCESS(
                "Created fictional demo data: 3 categories, 6 items, 18 units, "
                "8 basic users, 20 requests, 13 loans (including 2 overdue), "
                "a partial damaged return, and 4 maintenance records."
            )
        )
