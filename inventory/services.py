from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    AuditLog,
    BorrowRequest,
    EquipmentUnit,
    Loan,
    MaintenanceRecord,
    ReturnRecord,
    UnitAllocation,
)


def audit(actor, action, obj, detail=""):
    AuditLog.objects.create(
        actor=actor,
        action=action,
        reference_type=obj.__class__.__name__,
        reference_id=obj.pk,
        detail=detail,
    )


@transaction.atomic
def decide_request(req, actor, approve, reason=""):
    req = BorrowRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != BorrowRequest.Status.PENDING:
        raise ValidationError("Only pending requests can be decided.")

    req.decided_by = actor
    req.decided_at = timezone.now()
    req.decision_reason = reason

    if not approve:
        req.status = BorrowRequest.Status.REJECTED
        req.save()
        audit(actor, "REJECT", req, reason)
        return req

    allocations = []
    for line in req.lines.select_related("item"):
        available_units = list(
            EquipmentUnit.objects.select_for_update()
            .filter(
                item=line.item,
                status=EquipmentUnit.Status.AVAILABLE,
            )
            .order_by("asset_code")[: line.quantity]
        )
        if len(available_units) < line.quantity:
            raise ValidationError(
                f"Not enough available units for {line.item.name}."
            )
        allocations.extend((line, unit) for unit in available_units)

    req.status = BorrowRequest.Status.APPROVED
    req.save()

    for line, unit in allocations:
        UnitAllocation.objects.create(
            request_item=line,
            unit=unit,
        )
        unit.status = EquipmentUnit.Status.RESERVED
        unit.save(update_fields=["status"])

    audit(actor, "APPROVE", req, reason)
    return req


@transaction.atomic
def cancel_request(req, actor):
    req = BorrowRequest.objects.select_for_update().get(pk=req.pk)

    allowed_statuses = [
        BorrowRequest.Status.PENDING,
        BorrowRequest.Status.APPROVED,
    ]
    if req.owner_id != actor.pk or req.status not in allowed_statuses:
        raise ValidationError("This request cannot be cancelled.")

    if req.status == BorrowRequest.Status.APPROVED:
        allocation_ids = req.lines.filter(
            allocations__released_at__isnull=True,
        ).values_list("allocations__id", flat=True)

        for allocation_id in allocation_ids:
            allocation = UnitAllocation.objects.select_for_update().get(
                pk=allocation_id,
            )
            allocation.released_at = timezone.now()
            allocation.save(update_fields=["released_at"])

            allocation.unit.status = EquipmentUnit.Status.AVAILABLE
            allocation.unit.save(update_fields=["status"])

    req.status = BorrowRequest.Status.CANCELLED
    req.save(update_fields=["status"])
    audit(actor, "CANCEL", req)


@transaction.atomic
def issue_request(req, actor):
    req = BorrowRequest.objects.select_for_update().get(pk=req.pk)
    if req.status != BorrowRequest.Status.APPROVED:
        raise ValidationError("Only approved requests can be issued.")

    allocations = list(
        UnitAllocation.objects.select_for_update().filter(
            request_item__request=req,
            released_at__isnull=True,
        )
    )
    expected_units = req.lines.aggregate(
        quantity=Sum("quantity"),
    )["quantity"] or 0

    if len(allocations) != expected_units:
        raise ValidationError(
            "The request does not have complete unit allocations."
        )
    if timezone.localdate() > req.due_date:
        raise ValidationError("The agreed due date has passed.")

    loan = Loan.objects.create(
        request=req,
        issued_at=timezone.now(),
        issued_by=actor,
        due_date=req.due_date,
    )
    for allocation in allocations:
        allocation.unit.status = EquipmentUnit.Status.ISSUED
        allocation.unit.save(update_fields=["status"])

    req.status = BorrowRequest.Status.ISSUED
    req.save(update_fields=["status"])
    audit(actor, "ISSUE", loan)
    return loan


@transaction.atomic
def return_unit(allocation, actor, condition, return_date=None):
    allocation = UnitAllocation.objects.select_for_update().get(
        pk=allocation.pk,
    )
    has_loan = Loan.objects.filter(
        request=allocation.request_item.request,
    ).exists()
    if not has_loan or hasattr(allocation, "return_record"):
        raise ValidationError("This unit is not outstanding.")

    returned_at = (
        timezone.make_aware(datetime.combine(return_date, time.min))
        if return_date is not None
        else timezone.now()
    )
    record = ReturnRecord.objects.create(
        allocation=allocation,
        condition=condition,
        returned_at=returned_at,
        recorded_by=actor,
    )
    allocation.released_at = record.returned_at
    allocation.save(update_fields=["released_at"])

    unit = allocation.unit
    unit.condition = condition
    if condition == EquipmentUnit.Condition.DAMAGED:
        unit.status = EquipmentUnit.Status.MAINTENANCE
    else:
        unit.status = EquipmentUnit.Status.AVAILABLE
    unit.save(update_fields=["condition", "status"])

    if condition == EquipmentUnit.Condition.DAMAGED:
        maintenance = MaintenanceRecord.objects.create(
            unit=unit,
            problem="Damage reported at return",
            opened_by=actor,
        )
        audit(actor, "MAINTENANCE_OPEN", maintenance, "Damage reported at return")

    request = allocation.request_item.request
    has_outstanding_units = UnitAllocation.objects.filter(
        request_item__request=request,
        released_at__isnull=True,
        return_record__isnull=True,
    ).exists()
    if has_outstanding_units:
        request.status = BorrowRequest.Status.PARTIAL
    else:
        request.status = BorrowRequest.Status.RETURNED
    request.save(update_fields=["status"])

    audit(actor, "RETURN", record, condition)
    return record


