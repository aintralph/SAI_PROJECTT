from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from operations._test_helpers import (
    make_delivery,
    make_department,
    make_invoice,
    make_issue,
    make_material,
    make_need,
    make_po,
    make_pr,
    make_quotation,
    make_supplier,
    make_user,
)
from operations.models import Invoice, MaterialNeed, PurchaseOrder, PurchaseRequest


class OperationalPageSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.department = make_department()
        cls.material = make_material(stock="20")
        cls.supplier = make_supplier()
        cls.enduser = make_user("smoke_enduser", "enduser-maintenance-lead", cls.department)
        cls.pr_creator = make_user("smoke_pr", "pr-creator", cls.department)
        cls.odm = make_user("smoke_odm", "odm", cls.department)
        cls.specialist = make_user("smoke_specialist", "procurement-specialist", cls.department)
        cls.site = make_user("smoke_site", "procurement-site-lead", cls.department)
        cls.strategic = make_user("smoke_strategic", "procurement-strategic-lead", cls.department)
        cls.sic = make_user("smoke_sic", "sic-stockroom-gr-creator", cls.department)
        cls.dct = make_user("smoke_dct", "dct", cls.department)
        cls.accounting = make_user("smoke_accounting", "accounting-finance", cls.department)

        cls.need_open = make_need(cls.enduser, cls.department, cls.material, quantity="5")
        cls.need_owned = make_need(cls.enduser, cls.department, cls.material, quantity="5")
        cls.pr_pending = make_pr(cls.pr_creator, cls.need_owned)

        def chain(suffix, po_status, invoice_status=None):
            need = make_need(cls.enduser, cls.department, cls.material, quantity="5")
            pr = make_pr(cls.pr_creator, need, status=PurchaseRequest.Status.APPROVED)
            quotation = make_quotation(
                cls.specialist, pr, cls.supplier, selected=True
            )
            po = make_po(cls.sic, pr, quotation, status=po_status)
            delivery = make_delivery(cls.sic, po, quantity="1")
            invoice = None
            if invoice_status:
                invoice = make_invoice(cls.dct, po, status=invoice_status)
            return need, pr, quotation, po, delivery, invoice

        cls.need_resubmit, cls.pr_resubmit, cls.quote_resubmit, cls.po_resubmit, cls.delivery_resubmit, _ = chain(
            "resubmit", PurchaseOrder.Status.DRAFT
        )
        cls.need_site, cls.pr_site, cls.quote_site, cls.po_site, cls.delivery_site, _ = chain(
            "site", PurchaseOrder.Status.SITE_REVIEW
        )
        cls.need_strategic, cls.pr_strategic, cls.quote_strategic, cls.po_strategic, cls.delivery_strategic, _ = chain(
            "strategic", PurchaseOrder.Status.STRATEGIC_APPROVAL
        )
        cls.need_approved, cls.pr_approved, cls.quote_approved, cls.po_approved, cls.delivery_approved, cls.invoice_logged = chain(
            "approved", PurchaseOrder.Status.APPROVED, Invoice.Status.LOGGED
        )
        cls.need_handed, cls.pr_handed, cls.quote_handed, cls.po_handed, cls.delivery_handed, cls.invoice_handed = chain(
            "handed", PurchaseOrder.Status.APPROVED, Invoice.Status.HANDED_OFF
        )
        cls.issue = make_issue(
            cls.sic,
            cls.material,
            need=cls.need_owned,
            department=cls.department,
            quantity="1",
        )

    def _get(self, user, *args):
        self.client.force_login(user)
        for url in args:
            with self.subTest(user=user.username, url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_dashboard_and_records_render_for_every_operational_role(self):
        cases = [
            (self.enduser, ["dashboard", "records:needs", "records:requests", "records:deliveries", "records:stock", "records:issues"]),
            (self.pr_creator, ["dashboard", "records:needs", "records:requests"]),
            (self.odm, ["dashboard", "records:needs", "records:requests"]),
            (self.specialist, ["dashboard", "records:needs", "records:requests", "records:quotations", "records:orders", "records:stock"]),
            (self.site, ["dashboard", "records:requests", "records:quotations", "records:orders"]),
            (self.strategic, ["dashboard", "records:requests", "records:quotations", "records:orders"]),
            (self.sic, ["dashboard", "records:requests", "records:orders", "records:deliveries", "records:stock", "records:issues"]),
            (self.dct, ["dashboard", "records:orders", "records:deliveries", "records:invoices"]),
            (self.accounting, ["dashboard", "records:orders", "records:invoices"]),
        ]
        for user, urls in cases:
            self.client.force_login(user)
            for url_name in urls:
                if url_name == "dashboard":
                    url = reverse("dashboard")
                else:
                    url = reverse("records", args=[url_name.split(":", 1)[1]])
                with self.subTest(user=user.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_detail_pages_render_with_action_forms(self):
        self._get(
            self.enduser,
            reverse("need_detail", args=["needs", self.need_owned.reference]),
            reverse("need_detail", args=["requests", self.pr_pending.reference]),
            reverse("need_detail", args=["deliveries", self.delivery_approved.reference]),
            reverse("need_detail", args=["stock", self.material.code]),
            reverse("need_detail", args=["issues", self.issue.reference]),
        )
        self._get(
            self.odm,
            reverse("need_detail", args=["requests", self.pr_pending.reference]),
        )
        self._get(
            self.specialist,
            reverse("need_detail", args=["quotations", self.quote_site.reference]),
            reverse("need_detail", args=["orders", self.po_resubmit.reference]),
        )
        self._get(
            self.site,
            reverse("need_detail", args=["orders", self.po_site.reference]),
        )
        self._get(
            self.strategic,
            reverse("need_detail", args=["orders", self.po_strategic.reference]),
        )
        self._get(
            self.dct,
            reverse("need_detail", args=["invoices", self.invoice_logged.reference]),
        )
        self._get(
            self.accounting,
            reverse("need_detail", args=["invoices", self.invoice_handed.reference]),
        )

    def test_allowed_creation_forms_render(self):
        cases = [
            (self.enduser, "needs"),
            (self.pr_creator, "requests"),
            (self.specialist, "quotations"),
            (self.specialist, "orders"),
            (self.sic, "deliveries"),
            (self.sic, "stock"),
            (self.sic, "issues"),
            (self.dct, "invoices"),
        ]
        for user, module in cases:
            self.client.force_login(user)
            url = reverse("form_page", args=[module])
            with self.subTest(user=user.username, module=module):
                self.assertEqual(self.client.get(url).status_code, 200)
