import re
import threading
from decimal import Decimal

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from operations import services
from operations._test_helpers import (
    make_department,
    make_material,
    make_need,
    make_supplier,
    make_user,
)
from operations.models import (
    Delivery,
    Invoice,
    IssueSlip,
    MaterialNeed,
    PurchaseOrder,
    PurchaseRequest,
    Quotation,
    StockMovement,
)
from operations.references import next_reference


class ReferenceFormatTests(TestCase):
    def test_full_workflow_uses_each_prefix(self):
        department = make_department()
        material = make_material(stock="0")
        supplier = make_supplier()
        enduser = make_user("ref_enduser", "enduser-maintenance-lead", department)
        pr_creator = make_user("ref_pr", "pr-creator", department)
        odm = make_user("ref_odm", "odm", department)
        specialist = make_user("ref_specialist", "procurement-specialist", department)
        site = make_user("ref_site", "procurement-site-lead", department)
        strategic = make_user("ref_strategic", "procurement-strategic-lead", department)
        sic = make_user("ref_sic", "sic-stockroom-gr-creator", department)
        dct = make_user("ref_dct", "dct", department)
        accounting = make_user("ref_accounting", "accounting-finance", department)

        need = services.create_material_need(
            enduser,
            department=department,
            material=material,
            quantity="2",
            area="Line 1",
            description="Seal",
            needed_by="2026-12-31",
            purpose="Repair",
        )
        purchase_request = services.create_purchase_request(
            pr_creator, material_need=need
        )
        services.decide_purchase_request(
            odm,
            purchase_request=purchase_request,
            decision=PurchaseRequest.Status.APPROVED,
        )
        quotation = services.create_quotation(
            specialist,
            purchase_request=purchase_request,
            supplier=supplier,
            unit_price="10",
            total_amount="20",
        )
        services.select_quotation(specialist, quotation=quotation)
        purchase_order = services.create_purchase_order(
            specialist,
            purchase_request=purchase_request,
            quotation=quotation,
        )
        services.review_purchase_order(
            site, purchase_order=purchase_order, decision="endorse"
        )
        services.approve_purchase_order(
            strategic,
            purchase_order=purchase_order,
            decision=PurchaseOrder.Status.APPROVED,
        )
        delivery = services.record_delivery(
            sic,
            purchase_order=purchase_order,
            quantity_received="1",
            delivery_date="2026-11-27",
            gr_reference="GR-TEXT",
        )
        issue = services.record_issue(
            sic,
            material=material,
            quantity="1",
            material_need=need,
        )
        invoice = services.log_invoice(
            dct,
            purchase_order=purchase_order,
            delivery=delivery,
            invoice_number="SUP-100",
            amount="20",
        )
        services.handoff_invoice(dct, invoice=invoice)
        services.review_invoice(
            accounting,
            invoice=invoice,
            outcome=Invoice.Status.MATCHED,
        )

        pairs = [
            (need.reference, "MR"),
            (purchase_request.reference, "PR"),
            (quotation.reference, "QT"),
            (purchase_order.reference, "PO"),
            (delivery.reference, "DR"),
            (issue.reference, "IS"),
            (invoice.reference, "INV"),
        ]
        references = [reference for reference, _prefix in pairs]
        self.assertEqual(len(references), len(set(references)))
        for reference, prefix in pairs:
            self.assertRegex(reference, rf"^{prefix}-\d{{4}}-\d{{6}}$")


class AuditSurfaceTests(TestCase):
    def setUp(self):
        self.department = make_department()
        self.enduser = make_user("audit_enduser", "enduser-maintenance-lead", self.department)
        self.sysadmin = make_user("audit_sysadmin", "system-administrator", self.department)

    def test_operational_user_cannot_open_audit_surfaces(self):
        self.client.force_login(self.enduser)
        self.assertEqual(
            self.client.get(reverse("system_admin_audit_log")).status_code,
            403,
        )
        admin_response = self.client.get("/admin/operations/auditlog/")
        self.assertEqual(admin_response.status_code, 302)
        self.assertIn("/admin/login/", admin_response.url)

    def test_system_administrator_audit_surface_still_works(self):
        self.client.force_login(self.sysadmin)
        self.assertEqual(
            self.client.get(reverse("system_admin_audit_log")).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("system_admin_dashboard")).status_code,
            200,
        )


class ConcurrentReferenceTests(TransactionTestCase):
    def test_concurrent_reference_allocation_is_unique(self):
        results = []
        errors = []
        barrier = threading.Barrier(6)

        def worker():
            try:
                close_old_connections()
                barrier.wait(timeout=15)
                results.append(next_reference("MR"))
            except Exception as exc:  # pragma: no cover - surfaced by assertion below
                errors.append(exc)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 6)
        self.assertEqual(len(set(results)), 6)
        for reference in results:
            self.assertRegex(reference, r"^MR-\d{4}-\d{6}$")


class ConcurrentStockIssueTests(TransactionTestCase):
    def test_two_concurrent_issues_cannot_overdraw_stock(self):
        department = make_department()
        material = make_material(stock="10")
        enduser = make_user("concurrent_enduser", "enduser-maintenance-lead", department)
        sic = make_user("concurrent_sic", "sic-stockroom-gr-creator", department)
        need = make_need(enduser, department, material, quantity="10")

        results = []
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                close_old_connections()
                barrier.wait(timeout=15)
                issue = services.record_issue(
                    sic,
                    material=material,
                    quantity="6",
                    material_need=need,
                )
                results.append(issue.reference)
            except Exception as exc:  # pragma: no cover - surfaced by assertions below
                errors.append(exc)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], services.WorkflowError)
        material.refresh_from_db()
        self.assertEqual(material.stock_on_hand, Decimal("4"))
        self.assertEqual(IssueSlip.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)
