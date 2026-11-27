"""Shared fixtures for operational tests. Not production code."""

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from accounts.models import Department, UserProfile
from operations.models import (
    Delivery,
    Invoice,
    IssueSlip,
    Material,
    MaterialNeed,
    PurchaseOrder,
    PurchaseRequest,
    Quotation,
    Supplier,
)

TEST_PASSWORD = "SafeTestPassword123!"


def unique_ref(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def make_user(username, role_slug=None, department=None):
    user = get_user_model().objects.create_user(
        username=username,
        password=TEST_PASSWORD,
    )
    if role_slug:
        group, _ = Group.objects.get_or_create(name=role_slug)
        user.groups.add(group)
    if department is not None:
        UserProfile.objects.update_or_create(
            user=user,
            defaults={"department": department},
        )
    return user


def make_department(code="ENG", name="Engineering"):
    return Department.objects.get_or_create(code=code, defaults={"name": name})[0]


def make_material(code=None, name="Bearing", unit="pcs", stock="10", reorder="2"):
    return Material.objects.create(
        code=code or unique_ref("MAT"),
        name=name,
        unit=unit,
        stock_on_hand=Decimal(stock),
        reorder_level=Decimal(reorder),
    )


def make_supplier(code=None, name="Supplier One"):
    return Supplier.objects.create(code=code or unique_ref("SUP"), name=name)


def make_need(
    actor,
    department,
    material,
    *,
    quantity="5",
    status=MaterialNeed.Status.OPEN,
    sap_material_code="",
    description="Standard item",
):
    return MaterialNeed.objects.create(
        reference=unique_ref("MR"),
        department=department,
        material=material,
        area="Line 1",
        description=description,
        specification="",
        sap_material_code=sap_material_code,
        quantity=Decimal(quantity),
        purpose="Maintenance",
        needed_by="2026-12-31",
        status=status,
        created_by=actor,
    )


def make_pr(
    actor,
    need,
    *,
    status=PurchaseRequest.Status.PENDING_ODM,
    sap_pr_number="",
):
    return PurchaseRequest.objects.create(
        reference=unique_ref("PR"),
        material_need=need,
        sap_pr_number=sap_pr_number,
        status=status,
        created_by=actor,
    )


def make_quotation(
    actor,
    purchase_request,
    supplier,
    *,
    total="100",
    selected=False,
):
    return Quotation.objects.create(
        reference=unique_ref("QT"),
        purchase_request=purchase_request,
        supplier=supplier,
        unit_price=Decimal(total),
        total_amount=Decimal(total),
        is_selected=selected,
        selected_by=actor if selected else None,
        created_by=actor,
    )


def make_po(
    actor,
    purchase_request,
    quotation,
    *,
    status=PurchaseOrder.Status.SITE_REVIEW,
    sap_po_number="",
):
    return PurchaseOrder.objects.create(
        reference=unique_ref("PO"),
        purchase_request=purchase_request,
        quotation=quotation,
        supplier=quotation.supplier,
        sap_po_number=sap_po_number,
        total_amount=quotation.total_amount,
        status=status,
        created_by=actor,
    )


def make_delivery(actor, purchase_order, *, quantity="1", gr="GR-1"):
    return Delivery.objects.create(
        reference=unique_ref("DR"),
        purchase_order=purchase_order,
        quantity_received=Decimal(quantity),
        delivery_date="2026-11-27",
        sap_gr_number=gr,
        received_by=actor,
    )


def make_issue(actor, material, *, need=None, department=None, quantity="1", status=IssueSlip.Status.ISSUED):
    return IssueSlip.objects.create(
        reference=unique_ref("IS"),
        material=material,
        material_need=need,
        department=department,
        quantity_issued=Decimal(quantity),
        status=status,
        issued_by=actor,
    )


def make_invoice(actor, purchase_order, *, status=Invoice.Status.LOGGED, amount="100"):
    return Invoice.objects.create(
        reference=unique_ref("INV"),
        purchase_order=purchase_order,
        invoice_number="INV-001",
        amount=Decimal(amount),
        status=status,
        logged_by=actor,
    )
