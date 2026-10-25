from datetime import timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import (
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
from .services import cancel_request, decide_request, issue_request, return_unit

class WorkflowTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            "admin",
            password="ComplexPass!123",
            role=User.Role.ADMIN,
        )
        self.user = User.objects.create_user(
            "learner",
            password="ComplexPass!123",
        )
        self.cat = Category.objects.create(name="Test")
        self.item = CatalogItem.objects.create(
            category=self.cat,
            name="Laptop",
        )
        self.unit = EquipmentUnit.objects.create(
            asset_code="T-1",
            item=self.item,
        )
        SystemSetting.objects.create()

    def request(self):
        request = BorrowRequest.objects.create(
            owner=self.user,
            purpose="Class",
            due_date=timezone.localdate() + timedelta(days=3),
        )
        RequestItem.objects.create(
            request=request,
            item=self.item,
            quantity=1,
        )
        return request

    def test_allocation_reserves_and_cancel_releases(self):
        r = self.request()
        decide_request(r, self.admin, True)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, EquipmentUnit.Status.RESERVED)
        cancel_request(r, self.user)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, EquipmentUnit.Status.AVAILABLE)

    def test_only_one_request_can_reserve_last_unit(self):
        one = self.request()
        two = BorrowRequest.objects.create(
            owner=self.user,
            purpose="Second",
            due_date=one.due_date,
        )
        RequestItem.objects.create(
            request=two,
            item=self.item,
            quantity=1,
        )
        decide_request(one, self.admin, True)
        with self.assertRaises(ValidationError):
            decide_request(two, self.admin, True)
        active_allocations = UnitAllocation.objects.filter(
            released_at__isnull=True,
        ).count()
        self.assertEqual(active_allocations, 1)

    def test_issue_and_partial_return(self):
        r = self.request()
        decide_request(r, self.admin, True)
        loan = issue_request(r, self.admin)
        allocation = loan.allocations.get()
        return_unit(allocation, self.admin, EquipmentUnit.Condition.GOOD)
        r.refresh_from_db()
        self.assertEqual(r.status, BorrowRequest.Status.RETURNED)
        # Verify loan.allocations preserves history for borrowing slips and reports
        self.assertEqual(loan.allocations.count(), 1)
        self.assertEqual(loan.outstanding.count(), 0)

    def test_returned_unit_can_be_allocated_again(self):
        first_request = self.request()
        decide_request(first_request, self.admin, True)
        first_loan = issue_request(first_request, self.admin)
        first_allocation = first_loan.allocations.get()
        return_unit(
            first_allocation,
            self.admin,
            EquipmentUnit.Condition.GOOD,
        )

        next_request = self.request()
        decide_request(next_request, self.admin, True)

        first_allocation.refresh_from_db()
        next_request.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertIsNotNone(first_allocation.released_at)
        self.assertEqual(next_request.status, BorrowRequest.Status.APPROVED)
        self.assertEqual(self.unit.status, EquipmentUnit.Status.RESERVED)

    def test_damaged_return_enters_maintenance(self):
        r = self.request()
        decide_request(r, self.admin, True)
        loan = issue_request(r, self.admin)
        return_unit(
            loan.allocations.get(),
            self.admin,
            EquipmentUnit.Condition.DAMAGED,
        )
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, EquipmentUnit.Status.MAINTENANCE)

    def test_unit_retire_closes_open_maintenance(self):
        r = self.request()
        decide_request(r, self.admin, True)
        loan = issue_request(r, self.admin)
        return_unit(
            loan.allocations.get(),
            self.admin,
            EquipmentUnit.Condition.DAMAGED,
        )
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, EquipmentUnit.Status.MAINTENANCE)
        self.client.force_login(self.admin)
        response = self.client.post(f"/manage/inventory/units/{self.unit.pk}/retire/")
        self.assertRedirects(response, "/manage/inventory/")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, EquipmentUnit.Status.RETIRED)
        open_maintenances = self.unit.maintenance_records.filter(closed_at__isnull=True)
        self.assertEqual(open_maintenances.count(), 0)

    def test_close_maintenance_releases_unit_to_available(self):
        r = self.request()
        decide_request(r, self.admin, True)
        loan = issue_request(r, self.admin)
        return_unit(loan.allocations.get(), self.admin, EquipmentUnit.Condition.DAMAGED)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, EquipmentUnit.Status.MAINTENANCE)
        rec = self.unit.maintenance_records.filter(closed_at__isnull=True).first()

        self.client.force_login(self.admin)
        get_resp = self.client.get(f"/manage/maintenance/{rec.pk}/close/")
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, rec.unit.asset_code)
        self.assertContains(get_resp, f'action="/manage/maintenance/{rec.pk}/close/"')

        post_resp = self.client.post(
            f"/manage/maintenance/{rec.pk}/close/",
            {"action": "Replaced damaged cable and tested OK.", "outcome": "AVAILABLE"},
        )
        self.assertRedirects(post_resp, "/manage/maintenance/")
        rec.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertIsNotNone(rec.closed_at)
        self.assertEqual(rec.closed_by, self.admin)
        self.assertEqual(rec.action, "Replaced damaged cable and tested OK.")
        self.assertEqual(self.unit.status, EquipmentUnit.Status.AVAILABLE)

    def test_close_maintenance_can_retire_unserviceable_unit(self):
        r = self.request()
        decide_request(r, self.admin, True)
        loan = issue_request(r, self.admin)
        return_unit(loan.allocations.get(), self.admin, EquipmentUnit.Condition.DAMAGED)
        rec = self.unit.maintenance_records.filter(closed_at__isnull=True).first()

        self.client.force_login(self.admin)
        post_resp = self.client.post(
            f"/manage/maintenance/{rec.pk}/close/",
            {"action": "Screen cracked beyond repair.", "outcome": "RETIRED"},
        )
        self.assertRedirects(post_resp, "/manage/maintenance/")
        rec.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertIsNotNone(rec.closed_at)
        self.assertEqual(self.unit.status, EquipmentUnit.Status.RETIRED)

    def test_admin_can_approve_request_from_decision_form(self):
        request = self.request()
        self.client.force_login(self.admin)

        response = self.client.post(
            f"/manage/requests/{request.pk}/decision/",
            {"decision": "approve", "reason": "Stock confirmed."},
        )

        self.assertRedirects(response, "/manage/requests/")
        request.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.APPROVED)
        self.assertEqual(self.unit.status, EquipmentUnit.Status.RESERVED)

    def test_admin_can_register_multiple_available_units_with_unique_codes(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            "/manage/inventory/units/new/",
            {
                "asset_code": "JBL",
                "item": self.item.pk,
                "condition": EquipmentUnit.Condition.GOOD,
                "acquired_on": timezone.localdate().isoformat(),
                "quantity": 3,
            },
        )

        self.assertRedirects(response, "/manage/inventory/")
        units = EquipmentUnit.objects.filter(item=self.item).order_by("asset_code")
        self.assertEqual(units.count(), 4)
        self.assertEqual(
            list(units.values_list("asset_code", flat=True)),
            ["JBL-001", "JBL-002", "JBL-003", "T-1"],
        )
        self.assertEqual(
            EquipmentUnit.objects.filter(
                item=self.item,
                status=EquipmentUnit.Status.AVAILABLE,
            ).count(),
            4,
        )

    def test_modal_forms_post_back_to_their_own_action_url(self):
        self.client.force_login(self.admin)

        unit_response = self.client.get("/manage/inventory/units/new/")
        self.assertContains(
            unit_response,
            'action="/manage/inventory/units/new/"',
        )

        request = self.request()
        decision_response = self.client.get(
            f"/manage/requests/{request.pk}/decision/",
        )
        self.assertContains(
            decision_response,
            f'action="/manage/requests/{request.pk}/decision/"',
        )

    def test_approval_is_disabled_and_explained_when_stock_is_unavailable(self):
        request = self.request()
        self.unit.status = EquipmentUnit.Status.ISSUED
        self.unit.save(update_fields=["status"])
        self.client.force_login(self.admin)

        response = self.client.get(f"/manage/requests/{request.pk}/decision/")
        self.assertContains(response, "Not enough available units")
        self.assertContains(response, "0 available")

        response = self.client.post(
            f"/manage/requests/{request.pk}/decision/",
            {"decision": "approve", "reason": "Try to approve anyway."},
        )
        self.assertRedirects(response, "/manage/requests/")
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)

    def test_rejection_requires_a_reason(self):
        request = self.request()
        self.client.force_login(self.admin)

        response = self.client.post(
            f"/manage/requests/{request.pk}/decision/",
            {"decision": "reject", "reason": ""},
        )
        self.assertEqual(response.status_code, 200)
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.PENDING)
        self.assertContains(response, "Record a reason for this decision.")

    def test_admin_can_reject_request_with_a_reason(self):
        request = self.request()
        self.unit.status = EquipmentUnit.Status.ISSUED
        self.unit.save(update_fields=["status"])
        self.client.force_login(self.admin)

        response = self.client.post(
            f"/manage/requests/{request.pk}/decision/",
            {"decision": "reject", "reason": "Equipment is needed for an exam."},
        )

        self.assertRedirects(response, "/manage/requests/")
        request.refresh_from_db()
        self.assertEqual(request.status, BorrowRequest.Status.REJECTED)
        self.assertEqual(request.decision_reason, "Equipment is needed for an exam.")

    def test_registration_cannot_choose_admin_role(self):
        registration = {
            "username": "newstudent",
            "first_name": "New",
            "last_name": "Student",
            "email": "new@example.test",
            "phone": "",
            "password1": "LongDemoPassword!492",
            "password2": "LongDemoPassword!492",
        }
        response = self.client.post("/register/", registration)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newstudent")
        self.assertEqual(user.role, User.Role.BASIC_USER)

    def test_portal_is_owner_scoped_and_admin_role_is_required(self):
        other = User.objects.create_user("other", password="ComplexPass!123")
        BorrowRequest.objects.create(
            owner=other,
            purpose="PRIVATE PURPOSE",
            due_date=timezone.localdate() + timedelta(days=2),
        )
        self.client.login(username="learner", password="ComplexPass!123")
        response = self.client.get("/portal/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "PRIVATE PURPOSE")
        self.assertEqual(self.client.get("/portal/profile/").status_code, 200)
        self.assertEqual(self.client.get("/portal/requests/new/").status_code, 200)
        self.assertEqual(self.client.get("/manage/").status_code, 403)

    def test_browse_request_prefills_one_item_but_new_request_starts_blank(self):
        self.client.force_login(self.user)

        browse_response = self.client.get("/portal/")
        self.assertContains(browse_response, "/static/images/laptop.jpg")
        self.assertContains(
            browse_response,
            f"/portal/requests/new/?item={self.item.pk}",
        )

        direct_response = self.client.get("/portal/requests/new/")
        direct_lines = direct_response.context["lines"]
        self.assertIsNone(direct_lines[0]["item"].value())
        self.assertIsNone(direct_lines[1]["item"].value())
        self.assertIsNone(direct_lines[2]["item"].value())

        selected_response = self.client.get(
            "/portal/requests/new/",
            {"item": self.item.pk},
        )
        selected_lines = selected_response.context["lines"]
        self.assertEqual(
            int(selected_lines[0]["item"].value()),
            self.item.pk,
        )
        self.assertEqual(selected_lines[0]["quantity"].value(), 1)
        self.assertIsNone(selected_lines[1]["item"].value())
        self.assertIsNone(selected_lines[2]["item"].value())

    def test_unavailable_item_cannot_be_borrowed(self):
        # Set the unit to MAINTENANCE so available count becomes 0
        self.unit.status = EquipmentUnit.Status.MAINTENANCE
        self.unit.save(update_fields=["status"])

        self.client.force_login(self.user)

        # 1. Check portal catalog shows unavailable and disabled button
        browse_resp = self.client.get("/portal/")
        self.assertEqual(browse_resp.status_code, 200)
        self.assertContains(browse_resp, "Unavailable (0 Left)")
        self.assertContains(browse_resp, "Unavailable — Cannot Borrow")
        self.assertNotContains(browse_resp, f"/portal/requests/new/?item={self.item.pk}")

        # 2. Check preselecting unavailable item does not prefill and gives error
        prefill_resp = self.client.get(f"/portal/requests/new/?item={self.item.pk}")
        self.assertEqual(prefill_resp.status_code, 200)
        self.assertIsNone(prefill_resp.context["lines"][0]["item"].value())

        # 3. Check submitting request for unavailable item is rejected
        post_resp = self.client.post(
            "/portal/requests/new/",
            {
                "due_date": (timezone.localdate() + timedelta(days=2)).isoformat(),
                "purpose": "Study session",
                "line0-item": self.item.pk,
                "line0-quantity": 1,
            },
        )
        self.assertEqual(post_resp.status_code, 200)
        self.assertEqual(BorrowRequest.objects.filter(owner=self.user, purpose="Study session").count(), 0)

    def test_admin_pages_render_without_records(self):
        self.client.login(username="admin", password="ComplexPass!123")
        paths = [
            "/manage/",
            "/manage/requests/",
            "/manage/inventory/",
            "/manage/catalog/",
            "/manage/loans/",
            "/manage/returns/",
            "/manage/accounts/",
            "/manage/settings/",
            "/manage/audit/",
            "/manage/maintenance/",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_inventory_can_filter_by_category_item_and_status(self):
        other_category = Category.objects.create(name="Other category")
        other_item = CatalogItem.objects.create(
            category=other_category,
            name="Projector",
        )
        EquipmentUnit.objects.create(asset_code="P-1", item=other_item)
        self.client.force_login(self.admin)

        response = self.client.get(
            "/manage/inventory/",
            {
                "category": self.cat.pk,
                "item": self.item.pk,
                "status": EquipmentUnit.Status.AVAILABLE,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "T-1")
        self.assertNotContains(response, "P-1")
        self.assertContains(response, "All categories")
        self.assertContains(response, "All items")

    def test_requests_date_filter_presets(self):
        self.client.force_login(self.admin)
        r = self.request()

        # Test date preset filters
        for preset in ['today', 'yesterday', 'week', 'month']:
            resp = self.client.get(f'/manage/requests/?date_preset={preset}')
            self.assertEqual(resp.status_code, 200)
            self.assertIn('date_preset', resp.context)
            self.assertEqual(resp.context['date_preset'], preset)

        # Test custom range
        today = timezone.localdate().isoformat()
        resp_custom = self.client.get(f'/manage/requests/?start={today}&end={today}')
        self.assertEqual(resp_custom.status_code, 200)
        self.assertContains(resp_custom, r.owner.username)

    def test_deactivated_user_sees_deactivated_notice_on_login(self):
        # Admin deactivates the user
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        # Deactivated user attempts to log in
        resp = self.client.post(
            "/accounts/login/",
            {"username": self.user.username, "password": "ComplexPass!123"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Account Deactivated")
        self.assertContains(resp, "deactivated by an administrator")
        self.assertNotIn("_auth_user_id", self.client.session)

        # Reactivate user and verify login succeeds
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        resp_active = self.client.post(
            "/accounts/login/",
            {"username": self.user.username, "password": "ComplexPass!123"},
        )
        self.assertRedirects(resp_active, "/portal/")

    def test_loans_report_aggregations_and_computed_totals(self):
        # Create an approved and issued loan
        req = self.request()
        decide_request(req, self.admin, approve=True)
        loan = issue_request(req, self.admin)

        self.client.force_login(self.admin)
        response = self.client.get("/manage/loans/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("summary", response.context)
        summary = response.context["summary"]
        self.assertEqual(summary["total_loans"], 1)
        self.assertEqual(summary["total_units"], 1)
        self.assertGreaterEqual(summary["active_loans"], 0)
        self.assertContains(response, "Total Loans")
        self.assertContains(response, "Units Borrowed")

    def test_role_based_templates_and_reusable_components(self):
        # Admin dashboard uses admin base and includes admin sidebar
        self.client.force_login(self.admin)
        admin_resp = self.client.get("/manage/")
        self.assertEqual(admin_resp.status_code, 200)
        self.assertTemplateUsed(admin_resp, "manage/base.html")
        self.assertTemplateUsed(admin_resp, "components/admin_sidebar.html")
        self.assertTemplateUsed(admin_resp, "components/messages.html")

        # Borrower portal uses borrower base and includes user header
        self.client.force_login(self.user)
        user_resp = self.client.get("/portal/")
        self.assertEqual(user_resp.status_code, 200)
        self.assertTemplateUsed(user_resp, "portal/base.html")
        self.assertTemplateUsed(user_resp, "components/user_header.html")
        self.assertTemplateUsed(user_resp, "components/messages.html")

