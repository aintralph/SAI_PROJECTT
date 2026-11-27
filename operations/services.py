"""Transactional workflow services for the operational modules.

Every state-changing business action is performed here so views can stay thin
and the same rules apply to browser forms and any future API surface. Each
service writes its audit event in the same transaction as the business change.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .audit import record_audit
from .models import (
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
from .policies import has_all_capabilities
from .references import next_reference


class WorkflowError(Exception):
    """Raised when a requested workflow transition is not allowed."""


def _require(actor, *capabilities):
    if not has_all_capabilities(actor, *capabilities):
        raise WorkflowError("You do not have permission to perform this action.")


def _quantity(value):
    try:
        quantity = Decimal(str(value))
    except (ArithmeticError, ValueError):
        raise WorkflowError("Enter a valid quantity.") from None
    if quantity <= 0:
        raise WorkflowError("Quantity must be greater than zero.")
    return quantity


def _required(value, message):
    value = (value or "").strip()
    if not value:
        raise WorkflowError(message)
    return value


# ---------------------------------------------------------------------------
# Material needs
# ---------------------------------------------------------------------------

@transaction.atomic
def create_material_need(
    actor,
    *,
    department,
    material,
    quantity,
    area="",
    description="",
    specification="",
    sap_material_code="",
    needed_by=None,
    purpose="",
):
    _require(actor, "create_need")
    if needed_by is None:
        raise WorkflowError("A required-by date is required.")
    area = _required(area, "Area / machine is required.")
    purpose = _required(purpose, "Purpose is required.")
    quantity = _quantity(quantity)
    if not (sap_material_code or "").strip() and not (description or "").strip():
        raise WorkflowError(
            "Describe the material when no SAP material code is supplied."
        )

    need = MaterialNeed.objects.create(
        reference=next_reference("MR"),
        department=department,
        material=material,
        area=(area or "").strip(),
        description=(description or "").strip(),
        specification=(specification or "").strip(),
        sap_material_code=(sap_material_code or "").strip(),
        quantity=quantity,
        purpose=(purpose or "").strip(),
        needed_by=needed_by,
        status=MaterialNeed.Status.OPEN,
        created_by=actor,
    )
    record_audit(
        actor,
        "needs",
        need.reference,
        "Need created",
        new_status=need.status,
        details=f"material={material.code}; quantity={quantity}; department={department.code}",
    )
    return need


# ---------------------------------------------------------------------------
# Purchase requests and ODM decision
# ---------------------------------------------------------------------------

@transaction.atomic
def create_purchase_request(actor, *, material_need, sap_pr_number="", notes=""):
    _require(actor, "prepare_pr", "record_pr_reference")
    need = MaterialNeed.objects.select_for_update().get(pk=material_need.pk)
    if need.status != MaterialNeed.Status.OPEN:
        raise WorkflowError("Only an open material need can be prepared into a request.")
    if PurchaseRequest.objects.filter(material_need=need).exists():
        raise WorkflowError("A purchase request already exists for this need.")

    purchase_request = PurchaseRequest.objects.create(
        reference=next_reference("PR"),
        material_need=need,
        sap_pr_number=(sap_pr_number or "").strip(),
        status=PurchaseRequest.Status.PENDING_ODM,
        decision_notes=(notes or "").strip(),
        created_by=actor,
    )
    need.status = MaterialNeed.Status.CONVERTED
    need.save(update_fields=["status", "updated_at"])
    record_audit(
        actor,
        "requests",
        purchase_request.reference,
        "PR created",
        new_status=PurchaseRequest.Status.PENDING_ODM,
        details=f"linked_need={need.reference}; need_status={need.status}",
    )
    return purchase_request


@transaction.atomic
def decide_purchase_request(actor, *, purchase_request, decision, notes=""):
    _require(actor, "record_pr_decision")
    purchase_request = PurchaseRequest.objects.select_for_update().get(
        pk=purchase_request.pk
    )
    if purchase_request.status != PurchaseRequest.Status.PENDING_ODM:
        raise WorkflowError("This request is not awaiting an ODM decision.")

    allowed = {
        PurchaseRequest.Status.APPROVED,
        PurchaseRequest.Status.RETURNED,
        PurchaseRequest.Status.REJECTED,
    }
    if decision not in allowed:
        raise WorkflowError("Unsupported ODM decision.")
    if decision in {PurchaseRequest.Status.RETURNED, PurchaseRequest.Status.REJECTED}:
        notes = _required(notes, "A reason is required for return or rejection.")

    old_status = purchase_request.status
    purchase_request.status = decision
    purchase_request.decision_notes = (notes or "").strip()
    purchase_request.decided_by = actor
    purchase_request.decided_at = timezone.now()
    purchase_request.save(
        update_fields=["status", "decision_notes", "decided_by", "decided_at", "updated_at"]
    )
    record_audit(
        actor,
        "requests",
        purchase_request.reference,
        "ODM decision",
        old_status=old_status,
        new_status=decision,
        details=(notes or "").strip(),
    )
    return purchase_request


# ---------------------------------------------------------------------------
# Quotations and selection
# ---------------------------------------------------------------------------

@transaction.atomic
def create_quotation(
    actor,
    *,
    purchase_request,
    supplier,
    unit_price,
    total_amount,
    lead_time_days=None,
    payment_terms="",
    warranty="",
    score=None,
    notes="",
):
    _require(actor, "manage_quotations")
    purchase_request = PurchaseRequest.objects.select_for_update().get(
        pk=purchase_request.pk
    )
    if purchase_request.status != PurchaseRequest.Status.APPROVED:
        raise WorkflowError("Quotations can only be recorded for an approved request.")
    if PurchaseOrder.objects.filter(purchase_request=purchase_request).exists():
        raise WorkflowError("A purchase order already exists for this request.")
    if Decimal(str(unit_price)) < 0 or Decimal(str(total_amount)) < 0:
        raise WorkflowError("Quotation amounts cannot be negative.")

    quotation = Quotation.objects.create(
        reference=next_reference("QT"),
        purchase_request=purchase_request,
        supplier=supplier,
        unit_price=unit_price,
        total_amount=total_amount,
        lead_time_days=lead_time_days,
        payment_terms=(payment_terms or "").strip(),
        warranty=(warranty or "").strip(),
        score=score,
        notes=(notes or "").strip(),
        created_by=actor,
    )
    record_audit(
        actor,
        "quotations",
        quotation.reference,
        "Quotation recorded",
        details=f"request={purchase_request.reference}; supplier={supplier.code}",
    )
    return quotation


@transaction.atomic
def select_quotation(actor, *, quotation, notes=""):
    _require(actor, "manage_quotations")
    quotation_pk = quotation.pk
    purchase_request_id = Quotation.objects.values_list(
        "purchase_request_id", flat=True
    ).get(pk=quotation_pk)
    purchase_request = PurchaseRequest.objects.select_for_update().get(
        pk=purchase_request_id
    )
    quotation = Quotation.objects.select_for_update().get(pk=quotation_pk)
    if purchase_request.status != PurchaseRequest.Status.APPROVED:
        raise WorkflowError("Only quotations for an approved request can be selected.")
    if PurchaseOrder.objects.filter(purchase_request=purchase_request).exists():
        raise WorkflowError("The quotation cannot change after a purchase order exists.")

    siblings = Quotation.objects.select_for_update().filter(
        purchase_request=purchase_request
    )
    siblings.exclude(pk=quotation.pk).update(
        is_selected=False,
        selected_by=None,
        selected_at=None,
        selection_notes="",
    )
    quotation.is_selected = True
    quotation.selected_by = actor
    quotation.selected_at = timezone.now()
    quotation.selection_notes = (notes or "").strip()
    quotation.save(
        update_fields=[
            "is_selected",
            "selected_by",
            "selected_at",
            "selection_notes",
        ]
    )
    record_audit(
        actor,
        "quotations",
        quotation.reference,
        "Quotation selected",
        details=f"request={purchase_request.reference}; {quotation.selection_notes}".strip(),
    )
    return quotation


# ---------------------------------------------------------------------------
# Purchase order and two-stage approval
# ---------------------------------------------------------------------------

@transaction.atomic
def create_purchase_order(
    actor,
    *,
    purchase_request,
    quotation,
    sap_po_number="",
    total_amount=None,
):
    _require(actor, "record_po_reference")
    purchase_request = PurchaseRequest.objects.select_for_update().get(
        pk=purchase_request.pk
    )
    if purchase_request.status != PurchaseRequest.Status.APPROVED:
        raise WorkflowError("A purchase order requires an approved request.")
    if PurchaseOrder.objects.filter(purchase_request=purchase_request).exists():
        raise WorkflowError("A purchase order already exists for this request.")

    quotation = Quotation.objects.select_for_update().select_related("supplier").get(
        pk=quotation.pk
    )
    if quotation.purchase_request_id != purchase_request.id:
        raise WorkflowError("The quotation does not belong to this request.")
    if not quotation.is_selected:
        raise WorkflowError("Select the winning quotation before creating the order.")

    amount = Decimal(str(total_amount if total_amount is not None else quotation.total_amount))
    if amount < 0:
        raise WorkflowError("The order amount cannot be negative.")

    purchase_order = PurchaseOrder.objects.create(
        reference=next_reference("PO"),
        purchase_request=purchase_request,
        quotation=quotation,
        supplier=quotation.supplier,
        sap_po_number=(sap_po_number or "").strip(),
        total_amount=amount,
        status=PurchaseOrder.Status.SITE_REVIEW,
        created_by=actor,
    )
    record_audit(
        actor,
        "orders",
        purchase_order.reference,
        "PO created and sent for first review",
        new_status=PurchaseOrder.Status.SITE_REVIEW,
        details=f"request={purchase_request.reference}; quotation={quotation.reference}",
    )
    return purchase_order


@transaction.atomic
def review_purchase_order(actor, *, purchase_order, decision, notes=""):
    _require(actor, "review_po")
    purchase_order = PurchaseOrder.objects.select_for_update().get(
        pk=purchase_order.pk
    )
    if purchase_order.status != PurchaseOrder.Status.SITE_REVIEW:
        raise WorkflowError("This order is not awaiting first-stage review.")
    if decision not in {"endorse", "return"}:
        raise WorkflowError("Unsupported first-stage review decision.")
    if decision == "return":
        notes = _required(notes, "A reason is required when returning an order.")

    old_status = purchase_order.status
    purchase_order.reviewed_by = actor
    purchase_order.reviewed_at = timezone.now()
    purchase_order.review_notes = (notes or "").strip()
    if decision == "endorse":
        purchase_order.status = PurchaseOrder.Status.STRATEGIC_APPROVAL
    else:
        purchase_order.status = PurchaseOrder.Status.DRAFT
    purchase_order.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "updated_at",
        ]
    )
    record_audit(
        actor,
        "orders",
        purchase_order.reference,
        "Site Lead review",
        old_status=old_status,
        new_status=purchase_order.status,
        details=(notes or "").strip(),
    )
    return purchase_order


@transaction.atomic
def resubmit_purchase_order(actor, *, purchase_order):
    _require(actor, "record_po_reference")
    purchase_order = PurchaseOrder.objects.select_for_update().get(
        pk=purchase_order.pk
    )
    if purchase_order.status != PurchaseOrder.Status.DRAFT:
        raise WorkflowError("Only a returned draft order can be resubmitted.")
    old_status = purchase_order.status
    purchase_order.status = PurchaseOrder.Status.SITE_REVIEW
    purchase_order.save(update_fields=["status", "updated_at"])
    record_audit(
        actor,
        "orders",
        purchase_order.reference,
        "PO resubmitted for first review",
        old_status=old_status,
        new_status=purchase_order.status,
    )
    return purchase_order


@transaction.atomic
def approve_purchase_order(actor, *, purchase_order, decision, notes=""):
    _require(actor, "approve_po")
    purchase_order = PurchaseOrder.objects.select_for_update().get(
        pk=purchase_order.pk
    )
    if purchase_order.status != PurchaseOrder.Status.STRATEGIC_APPROVAL:
        raise WorkflowError("This order is not awaiting final approval.")
    if decision not in {PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.REJECTED}:
        raise WorkflowError("Unsupported final approval decision.")
    if decision == PurchaseOrder.Status.REJECTED:
        notes = _required(notes, "A reason is required when rejecting an order.")

    old_status = purchase_order.status
    purchase_order.status = decision
    purchase_order.approved_by = actor
    purchase_order.approved_at = timezone.now()
    purchase_order.approval_notes = (notes or "").strip()
    purchase_order.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "approval_notes",
            "updated_at",
        ]
    )
    record_audit(
        actor,
        "orders",
        purchase_order.reference,
        "Strategic Lead decision",
        old_status=old_status,
        new_status=decision,
        details=(notes or "").strip(),
    )
    return purchase_order


# ---------------------------------------------------------------------------
# Deliveries / goods receipts and stock
# ---------------------------------------------------------------------------

def _move_stock(actor, *, material, delta, reason, note="", delivery=None, issue=None):
    material.stock_on_hand = material.stock_on_hand + delta
    if material.stock_on_hand < 0:
        raise WorkflowError("This movement would make stock negative.")
    material.save(update_fields=["stock_on_hand"])
    return StockMovement.objects.create(
        material=material,
        delta=delta,
        reason=reason,
        note=(note or "").strip(),
        delivery=delivery,
        issue=issue,
        actor=actor,
    )


@transaction.atomic
def record_delivery(
    actor,
    *,
    purchase_order,
    quantity_received,
    delivery_date,
    gr_reference="",
    remarks="",
):
    _require(actor, "record_delivery", "record_gr")
    gr_reference = _required(gr_reference, "Enter the GR reference.")
    purchase_order = PurchaseOrder.objects.select_for_update().select_related(
        "purchase_request__material_need__material"
    ).get(pk=purchase_order.pk)
    if purchase_order.status not in {
        PurchaseOrder.Status.APPROVED,
        PurchaseOrder.Status.PARTIALLY_DELIVERED,
    }:
        raise WorkflowError("Deliveries can only be recorded against an approved order.")

    quantity = _quantity(quantity_received)
    need = purchase_order.purchase_request.material_need
    ordered = need.quantity
    already = (
        purchase_order.deliveries.aggregate(total=Sum("quantity_received"))["total"]
        or Decimal("0")
    )
    if already + quantity > ordered:
        raise WorkflowError(
            f"Delivery exceeds the ordered quantity of {ordered} {need.material.unit}."
        )

    material = Material.objects.select_for_update().get(pk=need.material_id)
    delivery = Delivery.objects.create(
        reference=next_reference("DR"),
        purchase_order=purchase_order,
        quantity_received=quantity,
        delivery_date=delivery_date,
        sap_gr_number=(gr_reference or "").strip(),
        remarks=(remarks or "").strip(),
        received_by=actor,
    )
    _move_stock(
        actor,
        material=material,
        delta=quantity,
        reason=StockMovement.Reason.DELIVERY_RECEIPT,
        note=f"GR reference: {(gr_reference or '').strip() or 'not supplied'}",
        delivery=delivery,
    )

    total_received = already + quantity
    old_status = purchase_order.status
    if total_received >= ordered:
        purchase_order.status = PurchaseOrder.Status.DELIVERED
        purchase_order.delivered_at = timezone.now()
    else:
        purchase_order.status = PurchaseOrder.Status.PARTIALLY_DELIVERED
    purchase_order.save(update_fields=["status", "delivered_at", "updated_at"])
    record_audit(
        actor,
        "deliveries",
        delivery.reference,
        "Delivery recorded",
        old_status=old_status,
        new_status=purchase_order.status,
        details=f"order={purchase_order.reference}; quantity={quantity}; GR reference recorded manually",
    )
    return delivery


@transaction.atomic
def adjust_stock(actor, *, material, delta, reason, note=""):
    _require(actor, "manage_stock")
    material = Material.objects.select_for_update().get(pk=material.pk)
    delta = Decimal(str(delta))
    if delta == 0:
        raise WorkflowError("The stock adjustment cannot be zero.")
    reason = _required(reason, "A reason is required for a stock adjustment.")
    movement = _move_stock(
        actor,
        material=material,
        delta=delta,
        reason=StockMovement.Reason.ADJUSTMENT,
        note=reason if not note else f"{reason}: {note}",
    )
    record_audit(
        actor,
        "stock",
        material.code,
        "Stock adjusted",
        details=f"delta={delta}; reason={reason}",
    )
    return movement


# ---------------------------------------------------------------------------
# Issues and end-user acknowledgement
# ---------------------------------------------------------------------------

@transaction.atomic
def record_issue(actor, *, material, quantity, department=None, material_need=None):
    _require(actor, "record_issue")
    quantity = _quantity(quantity)
    material = Material.objects.select_for_update().get(pk=material.pk)

    if material_need is not None:
        material_need = MaterialNeed.objects.select_for_update().get(
            pk=material_need.pk
        )
        if material_need.status == MaterialNeed.Status.CLOSED:
            raise WorkflowError("This material need is closed.")
        if material_need.material_id != material.id:
            raise WorkflowError("The issued material does not match the linked need.")
        department = material_need.department
    elif department is None:
        raise WorkflowError("Select a requesting department or linked material need.")

    if material.stock_on_hand < quantity:
        raise WorkflowError(
            f"Not enough stock. On hand: {material.stock_on_hand} {material.unit}."
        )

    issue = IssueSlip.objects.create(
        reference=next_reference("IS"),
        material=material,
        material_need=material_need,
        department=department,
        quantity_issued=quantity,
        status=IssueSlip.Status.ISSUED,
        issued_by=actor,
    )
    _move_stock(
        actor,
        material=material,
        delta=-quantity,
        reason=StockMovement.Reason.ISSUE,
        note=f"Issued to {department}",
        issue=issue,
    )
    record_audit(
        actor,
        "issues",
        issue.reference,
        "Issue slip created",
        new_status=IssueSlip.Status.ISSUED,
        details=f"material={material.code}; quantity={quantity}; department={department.code}",
    )
    return issue


@transaction.atomic
def acknowledge_issue(actor, *, issue, decision, remark=""):
    _require(actor, "acknowledge_issue")
    issue = IssueSlip.objects.select_for_update().get(pk=issue.pk)
    if issue.status != IssueSlip.Status.ISSUED:
        raise WorkflowError("This issue is not awaiting acknowledgement.")
    if not issue.material_need or issue.material_need.created_by_id != actor.id:
        raise WorkflowError("Only the requester who raised the linked need can acknowledge it.")
    if decision not in {"accept", "flag"}:
        raise WorkflowError("Unsupported acknowledgement decision.")
    if decision == "flag":
        remark = _required(remark, "Describe the condition issue.")

    old_status = issue.status
    issue.acknowledged_by = actor
    issue.acknowledged_at = timezone.now()
    issue.condition_notes = (remark or "").strip()
    if decision == "flag":
        issue.status = IssueSlip.Status.DISPUTED
    else:
        issue.status = IssueSlip.Status.ACKNOWLEDGED
        need = MaterialNeed.objects.select_for_update().get(pk=issue.material_need_id)
        need.status = MaterialNeed.Status.ISSUED
        need.save(update_fields=["status", "updated_at"])
    issue.save(
        update_fields=[
            "status",
            "acknowledged_by",
            "acknowledged_at",
            "condition_notes",
        ]
    )
    record_audit(
        actor,
        "issues",
        issue.reference,
        "Issue disputed" if decision == "flag" else "Issue acknowledged",
        old_status=old_status,
        new_status=issue.status,
        details=(remark or "").strip(),
    )
    return issue


# ---------------------------------------------------------------------------
# Invoices: DCT intake/handoff then Accounting review
# ---------------------------------------------------------------------------

@transaction.atomic
def log_invoice(
    actor,
    *,
    purchase_order,
    invoice_number,
    amount,
    remarks="",
    delivery=None,
):
    _require(actor, "log_invoice")
    purchase_order = PurchaseOrder.objects.select_for_update().get(
        pk=purchase_order.pk
    )
    if purchase_order.status not in {
        PurchaseOrder.Status.APPROVED,
        PurchaseOrder.Status.PARTIALLY_DELIVERED,
        PurchaseOrder.Status.DELIVERED,
    }:
        raise WorkflowError("Invoices can only be logged against an approved order.")
    amount = Decimal(str(amount))
    if amount < 0:
        raise WorkflowError("The invoice amount cannot be negative.")
    if delivery is not None and delivery.purchase_order_id != purchase_order.id:
        raise WorkflowError("The selected delivery does not belong to this order.")

    invoice = Invoice.objects.create(
        reference=next_reference("INV"),
        purchase_order=purchase_order,
        delivery=delivery,
        invoice_number=_required(invoice_number, "Enter the supplier invoice number."),
        amount=amount,
        status=Invoice.Status.LOGGED,
        remarks=(remarks or "").strip(),
        logged_by=actor,
    )
    record_audit(
        actor,
        "invoices",
        invoice.reference,
        "Invoice logged",
        new_status=Invoice.Status.LOGGED,
        details=f"order={purchase_order.reference}; invoice_number={invoice.invoice_number}",
    )
    return invoice


@transaction.atomic
def handoff_invoice(actor, *, invoice):
    _require(actor, "record_handoff")
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != Invoice.Status.LOGGED:
        raise WorkflowError("Only a newly logged invoice can be handed off.")
    old_status = invoice.status
    invoice.status = Invoice.Status.HANDED_OFF
    invoice.handed_off_by = actor
    invoice.handed_off_at = timezone.now()
    invoice.save(
        update_fields=["status", "handed_off_by", "handed_off_at", "updated_at"]
    )
    record_audit(
        actor,
        "invoices",
        invoice.reference,
        "Handed off to Accounting",
        old_status=old_status,
        new_status=invoice.status,
    )
    return invoice


@transaction.atomic
def review_invoice(actor, *, invoice, outcome, remarks=""):
    _require(actor, "review_invoice")
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != Invoice.Status.HANDED_OFF:
        raise WorkflowError("This invoice is not awaiting an Accounting review.")
    allowed = {
        Invoice.Status.MATCHED,
        Invoice.Status.DISPUTED,
        Invoice.Status.ON_HOLD,
        Invoice.Status.RETURNED,
    }
    if outcome not in allowed:
        raise WorkflowError("Unsupported Accounting outcome.")
    if outcome != Invoice.Status.MATCHED:
        remarks = _required(remarks, "Remarks are required for this outcome.")

    old_status = invoice.status
    invoice.status = outcome
    invoice.reviewed_by = actor
    invoice.reviewed_at = timezone.now()
    invoice.review_remarks = (remarks or "").strip()
    invoice.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_remarks",
            "updated_at",
        ]
    )
    record_audit(
        actor,
        "invoices",
        invoice.reference,
        "Accounting review",
        old_status=old_status,
        new_status=outcome,
        details=(remarks or "").strip(),
    )
    return invoice
