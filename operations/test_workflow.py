from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from operations import services
from operations._test_helpers import (
    make_delivery,
    make_department,
    make_issue,
    make_material,
    make_need,
    make_po,
    make_pr,
    make_quotation,
    make_supplier,
    make_user,
)
from operations.forms import MaterialNeedForm
from operations.models import (
    AuditLog,
    Delivery,
    Invoice,
    IssueSlip,
    Material,
    MaterialNeed,
    PurchaseOrder,
    PurchaseRequest,
    Quotation,
    StockMovement,
)


class MaterialNeedWorkflowTests(TestCase):
    def setUp(self):
        self.department = make_department()
        self.material = make_material(stock="10")
        self.enduser = make_user("need_user", "enduser-maintenance-lead", self.department)

    def _valid_data(self, **overrides):
        data = {
            "material": self.material.pk,
            "department": self.department.pk,
            "area": "Line 1",
            "sap_material_code": "SAP-123",
            "description": "",
            "specification": "",
            "quantity": "5",
            "needed_by": "2026-12-31",
            "purpose": "Maintenance",
        }
        data.update(overrides)
        return data

    def test_form_requires_required_by_purpose_and_positive_quantity(self):
        self.assertFalse(MaterialNeedForm(self._valid_data(needed_by="")).is_valid())
        self.assertFalse(MaterialNeedForm(self._valid_data(purpose="")).is_valid())
        self.assertFalse(MaterialNeedForm(self._valid_data(quantity="0")).is_valid())

    def test_non_standard_item_requires_description(self):
        form = MaterialNeedForm(
            self._valid_data(sap_material_code="", description="")
        )
        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)

        form = MaterialNeedForm(
            self._valid_data(sap_material_code="", description="Custom seal")
        )
        self.assertTrue(form.is_valid())

    def test_standard_item_can_omit_description(self):
        form = MaterialNeedForm(
            self._valid_data(sap_material_code="SAP-123", description="")
        )
        self.assertTrue(form.is_valid())

    def test_create_need_via_view_sets_owner_status_reference_and_audit(self):
        self.client.force_login(self.enduser)
        response = self.client.post(
            reverse("form_page", args=["needs"]),
            self._valid_data(sap_material_code="", description="Custom seal"),
        )
        self.assertEqual(response.status_code, 302)
        need = MaterialNeed.objects.get()
        self.assertEqual(need.created_by, self.enduser)
        self.assertEqual(need.status, MaterialNeed.Status.OPEN)
        self.assertRegex(need.reference, r"^MR-\d{4}-\d{6}$")
        self.assertEqual(
            AuditLog.objects.filter(
                module="needs", record_reference=need.reference, action="Need created"
            ).count(),
            1,
        )

    def test_references_are_unique_and_sequential(self):
        first = services.create_material_need(
            self.enduser,
            department=self.department,
            material=self.material,
            quantity="1",
            area="A",
            description="x",
            needed_by="2026-12-31",
            purpose="test",
        )
        second = services.create_material_need(
            self.enduser,
            department=self.department,
            material=self.material,
            quantity="1",
            area="A",
            description="x",
            needed_by="2026-12-31",
            purpose="test",
        )
        self.assertNotEqual(first.reference, second.reference)
        self.assertRegex(first.reference, r"^MR-\d{4}-\d{6}$")
        self.assertGreater(int(second.reference.rsplit("-", 1)[1]), int(first.reference.rsplit("-", 1)[1]))


class PurchaseRequestWorkflowTests(TestCase):
    def setUp(self):
        self.department = make_department()
        self.material = make_material()
        self.enduser = make_user("pr_enduser", "enduser-maintenance-lead", self.department)
        self.pr_creator = make_user("pr_creator", "pr-creator", self.department)
        self.odm = make_user("odm_user", "odm", self.department)
        self.need = make_need(self.enduser, self.department, self.material, quantity="5")

    def test_create_pr_from_open_need(self):
        purchase_request = services.create_purchase_request(
            self.pr_creator,
            material_need=self.need,
            sap_pr_number="PR-EXT-1",
        )
        self.need.refresh_from_db()
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.PENDING_ODM)
        self.assertEqual(self.need.status, MaterialNeed.Status.CONVERTED)
        self.assertRegex(purchase_request.reference, r"^PR-\d{4}-\d{6}$")
        self.assertEqual(
            AuditLog.objects.filter(
                module="requests",
                record_reference=purchase_request.reference,
                action="PR created",
            ).count(),
            1,
        )

    def test_duplicate_or_invalid_conversion_is_rejected(self):
        services.create_purchase_request(self.pr_creator, material_need=self.need)
        with self.assertRaises(services.WorkflowError):
            services.create_purchase_request(self.pr_creator, material_need=self.need)
        self.assertEqual(PurchaseRequest.objects.count(), 1)

        converted = make_need(
            self.enduser,
            self.department,
            self.material,
            status=MaterialNeed.Status.CONVERTED,
        )
        with self.assertRaises(services.WorkflowError):
            services.create_purchase_request(self.pr_creator, material_need=converted)

    def test_odm_decisions_and_reason_requirements(self):
        cases = [
            (PurchaseRequest.Status.APPROVED, ""),
            (PurchaseRequest.Status.RETURNED, "Missing specification"),
            (PurchaseRequest.Status.REJECTED, "Not required"),
        ]
        for index, (decision, notes) in enumerate(cases):
            need = make_need(
                self.enduser,
                self.department,
                self.material,
                quantity="1",
            )
            purchase_request = services.create_purchase_request(
                self.pr_creator,
                material_need=need,
            )
            services.decide_purchase_request(
                self.odm,
                purchase_request=purchase_request,
                decision=decision,
                notes=notes,
            )
            purchase_request.refresh_from_db()
            self.assertEqual(purchase_request.status, decision)
            self.assertEqual(purchase_request.decided_by, self.odm)
            self.assertEqual(purchase_request.decision_notes, notes)

        for decision in (PurchaseRequest.Status.RETURNED, PurchaseRequest.Status.REJECTED):
            need = make_need(
                self.enduser,
                self.department,
                self.material,
                quantity="1",
            )
            purchase_request = services.create_purchase_request(
                self.pr_creator,
                material_need=need,
            )
            with self.assertRaises(services.WorkflowError):
                services.decide_purchase_request(
                    self.odm,
                    purchase_request=purchase_request,
                    decision=decision,
                    notes="",
                )

    def test_odm_view_decision_does_not_edit_request_fields(self):
        purchase_request = services.create_purchase_request(
            self.pr_creator,
            material_need=self.need,
            sap_pr_number="ORIGINAL",
        )
        self.client.force_login(self.odm)
        response = self.client.post(
            reverse("request_decide", args=[purchase_request.reference]),
            {
                "decision": PurchaseRequest.Status.APPROVED,
                "decision_notes": "Approved",
                "sap_pr_number": "TAMPERED",
                "status": PurchaseRequest.Status.REJECTED,
            },
        )
        self.assertEqual(response.status_code, 302)
        purchase_request.refresh_from_db()
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.APPROVED)
        self.assertEqual(purchase_request.sap_pr_number, "ORIGINAL")


class PurchaseOrderWorkflowTests(TestCase):
    def setUp(self):
        self.department = make_department()
        self.material = make_material()
        self.supplier = make_supplier()
        self.enduser = make_user("po_enduser", "enduser-maintenance-lead", self.department)
        self.pr_creator = make_user("po_pr", "pr-creator", self.department)
        self.odm = make_user("po_odm", "odm", self.department)
        self.specialist = make_user("po_specialist", "procurement-specialist", self.department)
        self.site_lead = make_user("po_site", "procurement-site-lead", self.department)
        self.strategic = make_user("po_strategic", "procurement-strategic-lead", self.department)
        self.need = make_need(self.enduser, self.department, self.material, quantity="10")
        self.purchase_request = services.create_purchase_request(
            self.pr_creator, material_need=self.need
        )
        services.decide_purchase_request(
            self.odm,
            purchase_request=self.purchase_request,
            decision=PurchaseRequest.Status.APPROVED,
        )

    def _quote(self, total="100", supplier=None):
        return services.create_quotation(
            self.specialist,
            purchase_request=self.purchase_request,
            supplier=supplier or self.supplier,
            unit_price=total,
            total_amount=total,
        )

    def test_select_quotation_then_create_po(self):
        first = self._quote("90", make_supplier(name="Supplier A"))
        second = self._quote("80", make_supplier(name="Supplier B"))
        services.select_quotation(self.specialist, quotation=second, notes="Best price")
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_selected)
        self.assertTrue(second.is_selected)
        self.assertEqual(second.selected_by, self.specialist)
        self.assertIsNotNone(second.selected_at)

        purchase_order = services.create_purchase_order(
            self.specialist,
            purchase_request=self.purchase_request,
            quotation=second,
            sap_po_number="PO-EXT-1",
        )
        self.assertEqual(purchase_order.status, PurchaseOrder.Status.SITE_REVIEW)
        self.assertEqual(purchase_order.supplier, second.supplier)
        self.assertEqual(purchase_order.quotation, second)
        self.assertEqual(purchase_order.total_amount, Decimal("80"))

    def test_po_requires_selected_quotation(self):
        quotation = self._quote("100")
        with self.assertRaises(services.WorkflowError):
            services.create_purchase_order(
                self.specialist,
                purchase_request=self.purchase_request,
                quotation=quotation,
            )
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_two_stage_approval_is_ordered_and_separately_audited(self):
        quotation = self._quote("100")
        services.select_quotation(self.specialist, quotation=quotation)
        purchase_order = services.create_purchase_order(
            self.specialist,
            purchase_request=self.purchase_request,
            quotation=quotation,
        )

        with self.assertRaises(services.WorkflowError):
            services.approve_purchase_order(
                self.strategic,
                purchase_order=purchase_order,
                decision=PurchaseOrder.Status.APPROVED,
            )

        services.review_purchase_order(
            self.site_lead,
            purchase_order=purchase_order,
            decision="endorse",
            notes="Checked",
        )
        purchase_order.refresh_from_db()
        self.assertEqual(purchase_order.status, PurchaseOrder.Status.STRATEGIC_APPROVAL)
        self.assertEqual(purchase_order.reviewed_by, self.site_lead)

        services.approve_purchase_order(
            self.strategic,
            purchase_order=purchase_order,
            decision=PurchaseOrder.Status.APPROVED,
            notes="Approved",
        )
        purchase_order.refresh_from_db()
        self.assertEqual(purchase_order.status, PurchaseOrder.Status.APPROVED)
        self.assertEqual(purchase_order.approved_by, self.strategic)
        self.assertIsNotNone(purchase_order.reviewed_at)
        self.assertIsNotNone(purchase_order.approved_at)

        actions = list(
            AuditLog.objects.filter(
                module="orders", record_reference=purchase_order.reference
            ).values_list("action", flat=True)
        )
        self.assertEqual(actions.count("Site Lead review"), 1)
        self.assertEqual(actions.count("Strategic Lead decision"), 1)

        with self.assertRaises(services.WorkflowError):
            services.review_purchase_order(
                self.site_lead,
                purchase_order=purchase_order,
                decision="endorse",
            )
        with self.assertRaises(services.WorkflowError):
            services.approve_purchase_order(
                self.strategic,
                purchase_order=purchase_order,
                decision=PurchaseOrder.Status.APPROVED,
            )

    def test_return_and_resubmit(self):
        quotation = self._quote("100")
        services.select_quotation(self.specialist, quotation=quotation)
        purchase_order = services.create_purchase_order(
            self.specialist,
            purchase_request=self.purchase_request,
            quotation=quotation,
        )
        services.review_purchase_order(
            self.site_lead,
            purchase_order=purchase_order,
            decision="return",
            notes="Fix supplier code",
        )
        purchase_order.refresh_from_db()
        self.assertEqual(purchase_order.status, PurchaseOrder.Status.DRAFT)
        self.assertEqual(purchase_order.review_notes, "Fix supplier code")

        services.resubmit_purchase_order(self.specialist, purchase_order=purchase_order)
        purchase_order.refresh_from_db()
        self.assertEqual(purchase_order.status, PurchaseOrder.Status.SITE_REVIEW)

    def test_view_rejects_out_of_order_final_approval(self):
        quotation = self._quote("100")
        services.select_quotation(self.specialist, quotation=quotation)
        purchase_order = services.create_purchase_order(
            self.specialist,
            purchase_request=self.purchase_request,
            quotation=quotation,
        )
        self.client.force_login(self.strategic)
        response = self.client.post(
            reverse("order_approve", args=[purchase_order.reference]),
            {"decision": PurchaseOrder.Status.APPROVED, "notes": "", "status": "approved"},
        )
        self.assertEqual(response.status_code, 302)
        purchase_order.refresh_from_db()
        self.assertEqual(purchase_order.status, PurchaseOrder.Status.SITE_REVIEW)
        self.assertEqual(
            AuditLog.objects.filter(
                module="orders",
                record_reference=purchase_order.reference,
                action="Strategic Lead decision",
            ).count(),
            0,
        )


class DeliveryStockIssueWorkflowTests(TestCase):
    def setUp(self):
        self.department = make_department()
        self.material = make_material(stock="0")
        self.supplier = make_supplier()
        self.enduser = make_user("del_enduser", "enduser-maintenance-lead", self.department)
        self.other_enduser = make_user("del_other", "enduser-maintenance-lead", self.department)
        self.pr_creator = make_user("del_pr", "pr-creator", self.department)
        self.odm = make_user("del_odm", "odm", self.department)
        self.specialist = make_user("del_specialist", "procurement-specialist", self.department)
        self.site_lead = make_user("del_site", "procurement-site-lead", self.department)
        self.sic = make_user("del_sic", "sic-stockroom-gr-creator", self.department)
        self.need = make_need(self.enduser, self.department, self.material, quantity="10")
        self.purchase_request = services.create_purchase_request(
            self.pr_creator, material_need=self.need
        )
        services.decide_purchase_request(
            self.odm,
            purchase_request=self.purchase_request,
            decision=PurchaseRequest.Status.APPROVED,
        )
        self.quotation = services.create_quotation(
            self.specialist,
            purchase_request=self.purchase_request,
            supplier=self.supplier,
            unit_price="100",
            total_amount="100",
        )
        services.select_quotation(self.specialist, quotation=self.quotation)
        self.purchase_order = services.create_purchase_order(
            self.specialist,
            purchase_request=self.purchase_request,
            quotation=self.quotation,
        )
        services.review_purchase_order(
            self.site_lead, purchase_order=self.purchase_order, decision="endorse"
        )

    def _approve_po(self):
        strategic = make_user("del_strategic", "procurement-strategic-lead", self.department)
        services.approve_purchase_order(
            strategic,
            purchase_order=self.purchase_order,
            decision=PurchaseOrder.Status.APPROVED,
        )
        self.purchase_order.refresh_from_db()

    def test_partial_then_complete_delivery_with_typed_gr_reference(self):
        self._approve_po()
        first = services.record_delivery(
            self.sic,
            purchase_order=self.purchase_order,
            quantity_received="4",
            delivery_date="2026-11-27",
            gr_reference="GR-TYPED-001",
            remarks="Partial",
        )
        self.purchase_order.refresh_from_db()
        self.material.refresh_from_db()
        self.assertEqual(self.purchase_order.status, PurchaseOrder.Status.PARTIALLY_DELIVERED)
        self.assertEqual(self.material.stock_on_hand, Decimal("4"))
        self.assertEqual(first.sap_gr_number, "GR-TYPED-001")
        movement = StockMovement.objects.get(delivery=first)
        self.assertEqual(movement.delta, Decimal("4"))
        self.assertEqual(movement.reason, StockMovement.Reason.DELIVERY_RECEIPT)
        self.assertEqual(movement.actor, self.sic)

        second = services.record_delivery(
            self.sic,
            purchase_order=self.purchase_order,
            quantity_received="6",
            delivery_date="2026-11-28",
            gr_reference="GR-TYPED-002",
        )
        self.purchase_order.refresh_from_db()
        self.material.refresh_from_db()
        self.assertEqual(self.purchase_order.status, PurchaseOrder.Status.DELIVERED)
        self.assertIsNotNone(self.purchase_order.delivered_at)
        self.assertEqual(self.material.stock_on_hand, Decimal("10"))
        self.assertEqual(StockMovement.objects.filter(delivery__in=[first, second]).count(), 2)

        with self.assertRaises(services.WorkflowError):
            services.record_delivery(
                self.sic,
                purchase_order=self.purchase_order,
                quantity_received="1",
                delivery_date="2026-11-29",
                gr_reference="GR-EXTRA",
            )

    def test_over_delivery_and_unapproved_delivery_are_rejected(self):
        self._approve_po()
        with self.assertRaises(services.WorkflowError):
            services.record_delivery(
                self.sic,
                purchase_order=self.purchase_order,
                quantity_received="11",
                delivery_date="2026-11-27",
                gr_reference="GR-OVER",
            )
        self.assertEqual(Delivery.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(
            AuditLog.objects.filter(module="deliveries", action="Delivery recorded").count(),
            0,
        )

        self.purchase_order.status = PurchaseOrder.Status.SITE_REVIEW
        self.purchase_order.save(update_fields=["status"])
        with self.assertRaises(services.WorkflowError):
            services.record_delivery(
                self.sic,
                purchase_order=self.purchase_order,
                quantity_received="1",
                delivery_date="2026-11-27",
                gr_reference="GR-DRAFT",
            )

    def test_issue_stock_movement_and_owner_acknowledgement(self):
        self.material.stock_on_hand = Decimal("10")
        self.material.save(update_fields=["stock_on_hand"])

        issue = services.record_issue(
            self.sic,
            material=self.material,
            quantity="3",
            material_need=self.need,
        )
        self.material.refresh_from_db()
        self.assertEqual(self.material.stock_on_hand, Decimal("7"))
        self.assertEqual(issue.status, IssueSlip.Status.ISSUED)
        movement = StockMovement.objects.get(issue=issue)
        self.assertEqual(movement.delta, Decimal("-3"))
        self.assertEqual(movement.reason, StockMovement.Reason.ISSUE)

        with self.assertRaises(services.WorkflowError):
            services.acknowledge_issue(
                self.other_enduser, issue=issue, decision="accept"
            )
        with self.assertRaises(services.WorkflowError):
            services.acknowledge_issue(self.sic, issue=issue, decision="accept")

        services.acknowledge_issue(
            self.enduser, issue=issue, decision="accept", remark=""
        )
        issue.refresh_from_db()
        self.need.refresh_from_db()
        self.assertEqual(issue.status, IssueSlip.Status.ACKNOWLEDGED)
        self.assertEqual(issue.acknowledged_by, self.enduser)
        self.assertEqual(self.need.status, MaterialNeed.Status.ISSUED)
        self.assertEqual(
            AuditLog.objects.filter(
                module="issues", record_reference=issue.reference, action="Issue acknowledged"
            ).count(),
            1,
        )

    def test_dispute_is_a_separate_audited_event(self):
        self.material.stock_on_hand = Decimal("10")
        self.material.save(update_fields=["stock_on_hand"])
        issue = services.record_issue(
            self.sic,
            material=self.material,
            quantity="2",
            material_need=self.need,
        )
        services.acknowledge_issue(
            self.enduser, issue=issue, decision="flag", remark="Damaged seal"
        )
        issue.refresh_from_db()
        self.need.refresh_from_db()
        self.assertEqual(issue.status, IssueSlip.Status.DISPUTED)
        self.assertEqual(issue.condition_notes, "Damaged seal")
        self.assertEqual(self.need.status, MaterialNeed.Status.CONVERTED)
        self.assertEqual(
            AuditLog.objects.filter(
                module="issues", record_reference=issue.reference
            ).count(),
            2,
        )

    def test_negative_issue_and_adjustment_are_rejected(self):
        self.material.stock_on_hand = Decimal("2")
        self.material.save(update_fields=["stock_on_hand"])
        with self.assertRaises(services.WorkflowError):
            services.record_issue(
                self.sic,
                material=self.material,
                quantity="3",
                material_need=self.need,
            )
        self.material.refresh_from_db()
        self.assertEqual(self.material.stock_on_hand, Decimal("2"))
        self.assertEqual(StockMovement.objects.count(), 0)

        with self.assertRaises(services.WorkflowError):
            services.adjust_stock(
                self.sic,
                material=self.material,
                delta="-5",
                reason="Count correction",
            )
        self.material.refresh_from_db()
        self.assertEqual(self.material.stock_on_hand, Decimal("2"))
        self.assertEqual(StockMovement.objects.count(), 0)

        movement = services.adjust_stock(
            self.sic,
            material=self.material,
            delta="3",
            reason="Found in stores",
        )
        self.material.refresh_from_db()
        self.assertEqual(self.material.stock_on_hand, Decimal("5"))
        self.assertEqual(movement.reason, StockMovement.Reason.ADJUSTMENT)
        self.assertEqual(
            AuditLog.objects.filter(module="stock", action="Stock adjusted").count(),
            1,
        )


class InvoiceWorkflowTests(TestCase):
    def setUp(self):
        self.department = make_department()
        self.material = make_material(stock="10")
        self.supplier = make_supplier()
        self.enduser = make_user("inv_enduser", "enduser-maintenance-lead", self.department)
        self.pr_creator = make_user("inv_pr", "pr-creator", self.department)
        self.specialist = make_user("inv_specialist", "procurement-specialist", self.department)
        self.dct = make_user("inv_dct", "dct", self.department)
        self.accounting = make_user("inv_accounting", "accounting-finance", self.department)
        self.sic = make_user("inv_sic", "sic-stockroom-gr-creator", self.department)

        need = make_need(self.enduser, self.department, self.material, quantity="5")
        purchase_request = make_pr(
            self.pr_creator, need, status=PurchaseRequest.Status.APPROVED
        )
        quotation = make_quotation(
            self.specialist, purchase_request, self.supplier, selected=True
        )
        self.purchase_order = make_po(
            self.sic,
            purchase_request,
            quotation,
            status=PurchaseOrder.Status.APPROVED,
        )
        self.delivery = make_delivery(self.sic, self.purchase_order, quantity="5")

    def test_dct_intake_then_accounting_review_are_separate(self):
        invoice = services.log_invoice(
            self.dct,
            purchase_order=self.purchase_order,
            delivery=self.delivery,
            invoice_number="SUP-001",
            amount="100",
            remarks="Received",
        )
        self.assertEqual(invoice.status, Invoice.Status.LOGGED)

        with self.assertRaises(services.WorkflowError):
            services.review_invoice(
                self.accounting,
                invoice=invoice,
                outcome=Invoice.Status.MATCHED,
            )

        services.handoff_invoice(self.dct, invoice=invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.HANDED_OFF)
        self.assertEqual(invoice.handed_off_by, self.dct)

        services.review_invoice(
            self.accounting,
            invoice=invoice,
            outcome=Invoice.Status.MATCHED,
            remarks="Matched in full",
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.MATCHED)
        self.assertEqual(invoice.reviewed_by, self.accounting)
        self.assertEqual(invoice.remarks, "Received")
        self.assertEqual(invoice.review_remarks, "Matched in full")

        actions = list(
            AuditLog.objects.filter(
                module="invoices", record_reference=invoice.reference
            ).values_list("action", flat=True)
        )
        self.assertEqual(actions.count("Invoice logged"), 1)
        self.assertEqual(actions.count("Handed off to Accounting"), 1)
        self.assertEqual(actions.count("Accounting review"), 1)

    def test_invoice_requires_approved_order_and_matching_delivery(self):
        draft_need = make_need(
            self.enduser, self.department, self.material, quantity="1"
        )
        draft_pr = make_pr(
            self.pr_creator, draft_need, status=PurchaseRequest.Status.APPROVED
        )
        draft_quotation = make_quotation(
            self.specialist, draft_pr, self.supplier, selected=True
        )
        draft = make_po(
            self.sic,
            draft_pr,
            draft_quotation,
            status=PurchaseOrder.Status.DRAFT,
        )
        with self.assertRaises(services.WorkflowError):
            services.log_invoice(
                self.dct,
                purchase_order=draft,
                invoice_number="BAD",
                amount="1",
            )

        other_need = make_need(
            self.enduser, self.department, self.material, quantity="1"
        )
        other_pr = make_pr(
            self.pr_creator, other_need, status=PurchaseRequest.Status.APPROVED
        )
        other_quotation = make_quotation(
            self.specialist, other_pr, self.supplier, selected=True
        )
        other_po = make_po(
            self.sic,
            other_pr,
            other_quotation,
            status=PurchaseOrder.Status.APPROVED,
        )
        with self.assertRaises(services.WorkflowError):
            services.log_invoice(
                self.dct,
                purchase_order=other_po,
                delivery=self.delivery,
                invoice_number="BAD",
                amount="1",
            )

    def test_handoff_is_post_only_and_role_protected(self):
        invoice = services.log_invoice(
            self.dct,
            purchase_order=self.purchase_order,
            invoice_number="SUP-002",
            amount="100",
        )
        self.client.force_login(self.accounting)
        self.assertEqual(
            self.client.post(
                reverse("invoice_handoff", args=[invoice.reference]), {}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("invoice_handoff", args=[invoice.reference])).status_code,
            405,
        )

        self.client.force_login(self.dct)
        self.assertEqual(
            self.client.post(
                reverse("invoice_review", args=[invoice.reference]),
                {"outcome": Invoice.Status.MATCHED},
            ).status_code,
            403,
        )


class AuditRollbackTests(TestCase):
    def setUp(self):
        self.department = make_department()
        self.material = make_material(stock="10")
        self.enduser = make_user("rollback_enduser", "enduser-maintenance-lead", self.department)
        self.sic = make_user("rollback_sic", "sic-stockroom-gr-creator", self.department)
        self.need = make_need(self.enduser, self.department, self.material, quantity="2")

    def test_failed_audit_rolls_back_stock_and_business_rows(self):
        from unittest.mock import patch

        before_stock = self.material.stock_on_hand
        with patch(
            "operations.services.record_audit",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                services.record_issue(
                    self.sic,
                    material=self.material,
                    quantity="2",
                    material_need=self.need,
                )
        self.material.refresh_from_db()
        self.assertEqual(self.material.stock_on_hand, before_stock)
        self.assertEqual(IssueSlip.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(
            AuditLog.objects.filter(module="issues").count(),
            0,
        )
