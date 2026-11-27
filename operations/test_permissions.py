from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.roles import ROLE_ACCESS, capabilities_for, role_by_slug
from operations._test_helpers import (
    TEST_PASSWORD,
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
from operations.models import MaterialNeed, PurchaseOrder, PurchaseRequest
from operations.modules import MODULES, modules_for_user


EXPECTED_ACCESS = {
    "enduser-maintenance-lead": {
        "needs": "act",
        "requests": "read",
        "deliveries": "read",
        "stock": "read",
        "issues": "act",
    },
    "pr-creator": {"needs": "read", "requests": "act"},
    "odm": {"needs": "read", "requests": "act"},
    "procurement-specialist": {
        "needs": "read",
        "requests": "read",
        "quotations": "act",
        "orders": "act",
        "stock": "read",
    },
    "procurement-site-lead": {
        "requests": "read",
        "quotations": "read",
        "orders": "act",
    },
    "procurement-strategic-lead": {
        "requests": "read",
        "quotations": "read",
        "orders": "act",
    },
    "sic-stockroom-gr-creator": {
        "requests": "read",
        "orders": "read",
        "deliveries": "act",
        "stock": "act",
        "issues": "act",
    },
    "dct": {"orders": "read", "deliveries": "read", "invoices": "act"},
    "accounting-finance": {"orders": "read", "invoices": "act"},
}

ALL_MODULES = {
    "needs",
    "requests",
    "quotations",
    "orders",
    "deliveries",
    "stock",
    "issues",
    "invoices",
}


class RoleMatrixTests(TestCase):
    def test_operational_roles_match_the_required_matrix(self):
        actual = {
            role: access
            for role, access in ROLE_ACCESS.items()
            if role != "system-administrator"
        }
        self.assertEqual(actual, EXPECTED_ACCESS)

    def test_all_eight_modules_are_registered(self):
        self.assertEqual({module["key"] for module in MODULES}, ALL_MODULES)

    def test_system_administrator_role_and_workspace_are_unchanged(self):
        role = role_by_slug("system-administrator")
        self.assertEqual(role["capabilities"], ("manage_users", "view_audit"))
        self.assertEqual(ROLE_ACCESS["system-administrator"], {})
        self.assertEqual(capabilities_for("system-administrator"), ("manage_users", "view_audit"))

        department = make_department()
        sysadmin = make_user("sysadmin_matrix", "system-administrator", department)
        self.assertEqual(modules_for_user(sysadmin), [])
        self.client.force_login(sysadmin)
        self.assertRedirects(
            self.client.get(reverse("dashboard")),
            reverse("system_admin_dashboard"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.get(reverse("records", args=["needs"])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("system_admin_dashboard")).status_code,
            200,
        )

    def test_anonymous_users_are_denied(self):
        for url in (
            reverse("dashboard"),
            reverse("records", args=["needs"]),
            reverse("form_page", args=["needs"]),
            reverse("need_detail", args=["needs", "MR-2026-000001"]),
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login"), response.url)

    def test_each_role_is_denied_absent_modules_on_every_route(self):
        for role_slug, allowed in EXPECTED_ACCESS.items():
            user = make_user(f"user_{role_slug.replace('-', '_')}", role_slug)
            self.client.force_login(user)
            for module in ALL_MODULES - set(allowed):
                with self.subTest(role=role_slug, module=module):
                    self.assertEqual(
                        self.client.get(reverse("records", args=[module])).status_code,
                        403,
                    )
                    self.assertEqual(
                        self.client.get(reverse("form_page", args=[module])).status_code,
                        403,
                    )
                    self.assertEqual(
                        self.client.get(
                            reverse("need_detail", args=[module, "UNKNOWN-REF"])
                        ).status_code,
                        403,
                    )

    def test_read_only_roles_cannot_call_write_endpoints(self):
        cases = [
            ("procurement-site-lead", "order_approve"),
            ("procurement-strategic-lead", "order_review"),
            ("accounting-finance", "invoice_handoff"),
            ("dct", "invoice_review"),
            ("enduser-maintenance-lead", "request_decide"),
            ("pr-creator", "quotation_select"),
            ("procurement-specialist", "issue_acknowledge"),
        ]
        for role_slug, url_name in cases:
            user = make_user(f"readonly_{url_name}", role_slug)
            self.client.force_login(user)
            with self.subTest(role=role_slug, endpoint=url_name):
                response = self.client.post(
                    reverse(url_name, args=["UNKNOWN-REF"]),
                    {},
                )
                self.assertEqual(response.status_code, 403)

    def test_act_roles_cannot_reach_out_of_scope_creation_forms(self):
        cases = [
            ("odm", "requests"),
            ("procurement-site-lead", "orders"),
            ("procurement-strategic-lead", "orders"),
            ("dct", "deliveries"),
            ("accounting-finance", "invoices"),
            ("enduser-maintenance-lead", "issues"),
            ("procurement-specialist", "stock"),
        ]
        for role_slug, module in cases:
            user = make_user(f"nobuild_{role_slug.replace('-', '_')}_{module}", role_slug)
            self.client.force_login(user)
            with self.subTest(role=role_slug, module=module):
                self.assertEqual(
                    self.client.get(reverse("form_page", args=[module])).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(reverse("form_page", args=[module]), {}).status_code,
                    403,
                )


class ObjectScopingTests(TestCase):
    def setUp(self):
        self.department = make_department()
        self.material = make_material(stock="50")
        self.supplier = make_supplier()
        self.enduser_a = make_user("scope_a", "enduser-maintenance-lead", self.department)
        self.enduser_b = make_user("scope_b", "enduser-maintenance-lead", self.department)
        self.pr_creator = make_user("scope_pr", "pr-creator", self.department)
        self.sic = make_user("scope_sic", "sic-stockroom-gr-creator", self.department)

        self.need_a = make_need(self.enduser_a, self.department, self.material)
        self.need_b = make_need(self.enduser_b, self.department, self.material)
        self.need_c = make_need(self.enduser_a, self.department, self.material)
        self.pr_a = make_pr(self.pr_creator, self.need_a)
        self.issue_a = make_issue(
            self.sic,
            self.material,
            need=self.need_a,
            department=self.department,
            quantity="2",
        )

        approved_pr = make_pr(
            self.pr_creator,
            self.need_c,
            status=PurchaseRequest.Status.APPROVED,
        )
        quotation = make_quotation(self.sic, approved_pr, self.supplier, selected=True)
        self.po_a = make_po(
            self.sic,
            approved_pr,
            quotation,
            status=PurchaseOrder.Status.APPROVED,
        )
        self.delivery_a = make_delivery(self.sic, self.po_a)

    def test_end_user_cannot_open_another_users_need_or_request(self):
        self.client.force_login(self.enduser_b)
        self.assertEqual(
            self.client.get(reverse("need_detail", args=["needs", self.need_a.reference])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("need_detail", args=["requests", self.pr_a.reference])).status_code,
            404,
        )
        listing = self.client.get(reverse("records", args=["needs"]))
        self.assertContains(listing, self.need_b.reference)
        self.assertNotContains(listing, self.need_a.reference)

    def test_end_user_cannot_open_another_users_issue_delivery_or_acknowledge(self):
        self.client.force_login(self.enduser_b)
        self.assertEqual(
            self.client.get(reverse("need_detail", args=["issues", self.issue_a.reference])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("need_detail", args=["deliveries", self.delivery_a.reference])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("issue_acknowledge", args=[self.issue_a.reference]),
                {"decision": "accept"},
            ).status_code,
            404,
        )

    def test_owner_can_acknowledge_their_issue(self):
        self.client.force_login(self.enduser_a)
        response = self.client.post(
            reverse("issue_acknowledge", args=[self.issue_a.reference]),
            {"decision": "accept"},
        )
        self.assertEqual(response.status_code, 302)
        self.issue_a.refresh_from_db()
        self.assertEqual(self.issue_a.status, "acknowledged")

    def test_forged_owner_and_status_fields_are_ignored(self):
        self.client.force_login(self.enduser_a)
        response = self.client.post(
            reverse("form_page", args=["needs"]),
            {
                "material": self.material.pk,
                "department": self.department.pk,
                "area": "Line 2",
                "sap_material_code": "",
                "description": "Non-standard seal",
                "specification": "",
                "quantity": "3",
                "needed_by": "2026-12-31",
                "purpose": "Repair",
                "created_by": self.enduser_b.pk,
                "status": MaterialNeed.Status.CONVERTED,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = MaterialNeed.objects.exclude(
            pk__in=[self.need_a.pk, self.need_b.pk, self.need_c.pk]
        ).get()
        self.assertEqual(created.created_by, self.enduser_a)
        self.assertEqual(created.status, MaterialNeed.Status.OPEN)
