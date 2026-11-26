import uuid

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.roles import role_by_slug
from accounts.views import render_access_denied

from .forms import (
    AccountingReviewForm,
    AcknowledgeIssueForm,
    DeliveryForm,
    DemonstrationForm,
    InvoiceForm,
    IssueSlipForm,
    MaterialNeedForm,
    ODMDecisionForm,
    POApprovalForm,
    POReviewForm,
    PurchaseOrderForm,
    PurchaseRequestForm,
    QuotationForm,
    SelectQuotationForm,
)
from .models import (
    AuditLog,
    Delivery,
    Invoice,
    IssueSlip,
    MaterialNeed,
    PurchaseOrder,
    PurchaseRequest,
    Quotation,
)
from .modules import (
    MODULES,
    ROLE_LABELS,
    modules_for_user,
    role_slugs_for_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role_context(user):
    role_slugs = role_slugs_for_user(user)
    if not role_slugs:
        return None
    return {"label": ", ".join(ROLE_LABELS[slug] for slug in role_slugs)}


def _make_ref(prefix):
    year = timezone.now().year
    short = uuid.uuid4().hex[:5].upper()
    return f"{prefix}-{year}-{short}"


def _audit(actor, module, record_reference, action, old_status="", new_status="", details=""):
    AuditLog.objects.create(
        actor=actor,
        module=module,
        record_reference=record_reference,
        action=action,
        old_status=old_status,
        new_status=new_status,
        details=details,
    )


def _base(request, module_key):
    """Return (permitted_module, nav_modules) or None if no access."""
    nav_modules = modules_for_user(request.user)
    permitted = next((m for m in nav_modules if m["key"] == module_key), None)
    return permitted, nav_modules


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    modules = modules_for_user(request.user)
    role_slugs = role_slugs_for_user(request.user)

    if request.user.is_superuser:
        return redirect("admin:index")

    role = None
    description = None
    if role_slugs:
        role = {"label": ", ".join(ROLE_LABELS[slug] for slug in role_slugs)}
        if len(role_slugs) == 1:
            role_definition = role_by_slug(role_slugs[0])
            if role_definition:
                description = role_definition["purpose"]

    # --- real metrics ---
    open_needs = MaterialNeed.objects.filter(
        status=MaterialNeed.Status.OPEN
    ).count()

    awaiting = 0
    for slug in role_slugs:
        if slug == "pr-creator":
            awaiting += PurchaseRequest.objects.filter(
                status__in=[PurchaseRequest.Status.DRAFT,
                            PurchaseRequest.Status.RETURNED]
            ).count()
        elif slug == "odm":
            awaiting += PurchaseRequest.objects.filter(
                status=PurchaseRequest.Status.PENDING_ODM
            ).count()
        elif slug == "procurement-specialist":
            awaiting += PurchaseOrder.objects.filter(
                status=PurchaseOrder.Status.DRAFT
            ).count()
        elif slug == "procurement-site-lead":
            awaiting += PurchaseOrder.objects.filter(
                status=PurchaseOrder.Status.SITE_REVIEW
            ).count()
        elif slug == "procurement-strategic-lead":
            awaiting += PurchaseOrder.objects.filter(
                status=PurchaseOrder.Status.STRATEGIC_APPROVAL
            ).count()
        elif slug == "sic-stockroom-gr-creator":
            awaiting += IssueSlip.objects.filter(
                status=IssueSlip.Status.ISSUED
            ).count()
        elif slug == "dct":
            awaiting += Invoice.objects.filter(
                status=Invoice.Status.LOGGED
            ).count()
        elif slug == "accounting-finance":
            awaiting += Invoice.objects.filter(
                status=Invoice.Status.HANDED_OFF
            ).count()
        elif slug == "enduser-maintenance-lead":
            awaiting += IssueSlip.objects.filter(
                status=IssueSlip.Status.ISSUED
            ).count()

    delivered = Delivery.objects.count()

    from django.db.models import F
    from .models import Material
    stock_alerts = Material.objects.filter(
        stock_on_hand__lte=F("reorder_level")
    ).count()

    records_connected = True

    action_module = next(
        (m for m in modules if m["access"] == "act"), None
    )
    primary_action = (
        {"label": "Open " + action_module["label"], "url": action_module["url"]}
        if action_module
        else {"label": "Dashboard", "url": request.path}
    )

    metrics = [
        {"label": "Open needs", "value": open_needs, "unit": "records", "source": "From your requests"},
        {"label": "Awaiting my action", "value": awaiting, "unit": "records", "source": "Acknowledgement pending"},
        {"label": "Delivered", "value": delivered, "unit": "records", "source": "From recorded receipts"},
        {"label": "Stock alerts", "value": stock_alerts, "unit": "items", "source": "From stock on hand"},
    ]

    # queue: items needing this user's action
    queue = _build_queue(role_slugs)

    return render(request, "operations/dashboard.html", {
        "role": role,
        "role_description": description,
        "records_connected": records_connected,
        "metrics": metrics,
        "modules": modules,
        "module_count": len(modules),
        "queue": queue,
        "status": {"source": "PostgreSQL", "last_sync": timezone.now().strftime("%Y-%m-%d %H:%M")},
        "crumb_parent": "Workspace",
        "crumb_current": "Dashboard",
        "nav_modules": modules,
        "active_module": None,
        "primary_action": primary_action,
    })



def _build_queue(role_slugs):
    queue = []
    for slug in role_slugs:
        if slug == "pr-creator":
            for need in MaterialNeed.objects.filter(status=MaterialNeed.Status.OPEN)[:5]:
                queue.append({"title": need.reference, "subtitle": "Material need awaiting PR"})
        elif slug == "odm":
            for pr in PurchaseRequest.objects.filter(status=PurchaseRequest.Status.PENDING_ODM)[:5]:
                queue.append({"title": pr.reference, "subtitle": "Purchase request awaiting your decision"})
        elif slug == "procurement-specialist":
            for po in PurchaseOrder.objects.filter(status=PurchaseOrder.Status.DRAFT)[:5]:
                queue.append({"title": po.reference, "subtitle": "Purchase order draft awaiting submission"})
        elif slug == "procurement-site-lead":
            for po in PurchaseOrder.objects.filter(status=PurchaseOrder.Status.SITE_REVIEW)[:5]:
                queue.append({"title": po.reference, "subtitle": "Purchase order awaiting your review"})
        elif slug == "procurement-strategic-lead":
            for po in PurchaseOrder.objects.filter(status=PurchaseOrder.Status.STRATEGIC_APPROVAL)[:5]:
                queue.append({"title": po.reference, "subtitle": "Purchase order awaiting your approval"})
        elif slug == "sic-stockroom-gr-creator":
            for slip in IssueSlip.objects.filter(status=IssueSlip.Status.ISSUED)[:5]:
                queue.append({"title": slip.reference, "subtitle": "Issue slip awaiting end-user acknowledgement"})
        elif slug == "dct":
            for inv in Invoice.objects.filter(status=Invoice.Status.LOGGED)[:5]:
                queue.append({"title": inv.reference, "subtitle": "Invoice awaiting handoff to Accounting"})
        elif slug == "accounting-finance":
            for inv in Invoice.objects.filter(status=Invoice.Status.HANDED_OFF)[:5]:
                queue.append({"title": inv.reference, "subtitle": "Invoice awaiting your review"})
        elif slug == "enduser-maintenance-lead":
            for slip in IssueSlip.objects.filter(status=IssueSlip.Status.ISSUED)[:5]:
                queue.append({"title": slip.reference, "subtitle": "Issue slip awaiting your acknowledgement"})
    return queue


# ---------------------------------------------------------------------------
# Generic records list
# ---------------------------------------------------------------------------

_MODULE_COLUMNS = {
    "needs": [
        {"label": "Reference", "kind": "reference"},
        {"label": "Material"},
        {"label": "Quantity", "kind": "number"},
        {"label": "Needed by"},
        {"label": "Status"},
    ],
    "requests": [
        {"label": "Reference", "kind": "reference"},
        {"label": "Linked need", "kind": "reference"},
        {"label": "SAP PR"},
        {"label": "Status"},
    ],
    "quotations": [
        {"label": "Reference", "kind": "reference"},
        {"label": "Supplier"},
        {"label": "Total", "kind": "number"},
        {"label": "Selected"},
    ],
    "orders": [
        {"label": "Reference", "kind": "reference"},
        {"label": "Supplier"},
        {"label": "Total", "kind": "number"},
        {"label": "Status"},
    ],
    "deliveries": [
        {"label": "Reference", "kind": "reference"},
        {"label": "Purchase order", "kind": "reference"},
        {"label": "Qty received", "kind": "number"},
        {"label": "GR number"},
        {"label": "Date"},
    ],
    "issues": [
        {"label": "Reference", "kind": "reference"},
        {"label": "Material"},
        {"label": "Qty issued", "kind": "number"},
        {"label": "Status"},
    ],
    "invoices": [
        {"label": "Reference", "kind": "reference"},
        {"label": "Invoice no."},
        {"label": "Amount", "kind": "number"},
        {"label": "Status"},
    ],
}


def _rows_for_module(module_key):
    if module_key == "needs":
        return [
            [
                {"kind": "reference", "value": n.reference},
                {"kind": "text", "value": str(n.material)},
                {"kind": "number", "value": str(n.quantity)},
                {"kind": "text", "value": str(n.needed_by) if n.needed_by else "—"},
                {"kind": "status", "value": n.get_status_display()},
            ]
            for n in MaterialNeed.objects.select_related("material").all()
        ]
    if module_key == "requests":
        return [
            [
                {"kind": "reference", "value": pr.reference},
                {"kind": "reference", "value": pr.material_need.reference},
                {"kind": "text", "value": pr.sap_pr_number or "Pending"},
                {"kind": "status", "value": pr.get_status_display()},
            ]
            for pr in PurchaseRequest.objects.select_related("material_need").all()
        ]
    if module_key == "quotations":
        return [
            [
                {"kind": "reference", "value": q.reference},
                {"kind": "text", "value": str(q.supplier)},
                {"kind": "number", "value": str(q.total_amount)},
                {"kind": "text", "value": "Yes" if q.is_selected else "No"},
            ]
            for q in Quotation.objects.select_related("supplier").all()
        ]
    if module_key == "orders":
        return [
            [
                {"kind": "reference", "value": po.reference},
                {"kind": "text", "value": str(po.supplier)},
                {"kind": "number", "value": str(po.total_amount)},
                {"kind": "status", "value": po.get_status_display()},
            ]
            for po in PurchaseOrder.objects.select_related("supplier").all()
        ]
    if module_key == "deliveries":
        return [
            [
                {"kind": "reference", "value": d.reference},
                {"kind": "reference", "value": d.purchase_order.reference},
                {"kind": "number", "value": str(d.quantity_received)},
                {"kind": "text", "value": d.sap_gr_number or "—"},
                {"kind": "text", "value": str(d.delivery_date)},
            ]
            for d in Delivery.objects.select_related("purchase_order").all()
        ]
    if module_key == "issues":
        return [
            [
                {"kind": "reference", "value": s.reference},
                {"kind": "text", "value": str(s.material)},
                {"kind": "number", "value": str(s.quantity_issued)},
                {"kind": "status", "value": s.get_status_display()},
            ]
            for s in IssueSlip.objects.select_related("material").all()
        ]
    if module_key == "invoices":
        return [
            [
                {"kind": "reference", "value": i.reference},
                {"kind": "text", "value": i.invoice_number},
                {"kind": "number", "value": str(i.amount)},
                {"kind": "status", "value": i.get_status_display()},
            ]
            for i in Invoice.objects.all()
        ]
    return []


@login_required
def records(request, module):
    module_definition = next((e for e in MODULES if e["key"] == module), None)
    if module_definition is None:
        raise Http404("Unknown module.")

    permitted_module, nav_modules = _base(request, module)
    if permitted_module is None:
        return render_access_denied(request)

    rows = _rows_for_module(module)
    return render(request, "operations/records.html", {
        "module": permitted_module,
        "columns": _MODULE_COLUMNS.get(module, []),
        "rows": rows,
        "record_count": len(rows),
        "records_connected": True,
        "data_source": "PostgreSQL",
        "title": "No records yet",
        "body": "No records have been created for this module.",
        "role": _role_context(request.user),
        "crumb_parent": "Workspace",
        "crumb_current": permitted_module["label"],
        "nav_modules": nav_modules,
        "active_module": module,
    })


# ---------------------------------------------------------------------------
# Record detail — dispatches by module
# ---------------------------------------------------------------------------

@login_required
def need_detail(request, module, reference):
    module_definition = next((e for e in MODULES if e["key"] == module), None)
    if module_definition is None:
        raise Http404("Unknown module.")

    permitted_module, nav_modules = _base(request, module)
    if permitted_module is None:
        return render_access_denied(request)

    ctx = {
        "module": permitted_module,
        "reference": reference,
        "role": _role_context(request.user),
        "crumb_parent": permitted_module["label"],
        "crumb_current": reference,
        "nav_modules": nav_modules,
        "active_module": module,
        "chain": [],
        "actions": [],
        "action_message": "",
    }

    if module == "needs":
        return _detail_need(request, reference, permitted_module, ctx)
    if module == "requests":
        return _detail_pr(request, reference, permitted_module, ctx)
    if module == "quotations":
        return _detail_quotation(request, reference, permitted_module, ctx)
    if module == "orders":
        return _detail_po(request, reference, permitted_module, ctx)
    if module == "deliveries":
        return _detail_delivery(request, reference, permitted_module, ctx)
    if module == "issues":
        return _detail_issue(request, reference, permitted_module, ctx)
    if module == "invoices":
        return _detail_invoice(request, reference, permitted_module, ctx)

    ctx.update({"status": "Unknown module", "fields": []})
    return render(request, "operations/need_detail.html", ctx)


# --- Stage 1 detail: Material Need ---
def _detail_need(request, reference, permitted_module, ctx):
    obj = get_object_or_404(MaterialNeed, reference=reference)
    ctx["status"] = obj.get_status_display()
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Department", "value": str(obj.department)},
        {"label": "Material", "value": str(obj.material)},
        {"label": "Area", "value": obj.area or "—"},
        {"label": "Description", "value": obj.description or "—"},
        {"label": "Specification", "value": obj.specification or "—"},
        {"label": "Quantity", "value": str(obj.quantity)},
        {"label": "Needed by", "value": str(obj.needed_by) if obj.needed_by else "—"},
        {"label": "Purpose", "value": obj.purpose or "—"},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Raised by", "value": obj.created_by.get_full_name() or obj.created_by.username},
        {"label": "Created", "value": obj.created_at.strftime("%Y-%m-%d %H:%M")},
    ]
    ctx["chain"] = [
        {"module_key": "requests", "reference": pr.reference}
        for pr in obj.purchase_requests.all()
    ]
    if permitted_module["access"] == "act" and obj.status == MaterialNeed.Status.OPEN:
        ctx["actions"] = [{"url": "#", "label": "Edit need (coming soon)"}]
    else:
        ctx["action_message"] = "No actions available for this record in its current status."
    return render(request, "operations/need_detail.html", ctx)


# --- Stage 2 detail: Purchase Request ---
def _detail_pr(request, reference, permitted_module, ctx):
    obj = get_object_or_404(PurchaseRequest, reference=reference)
    ctx["status"] = obj.get_status_display()
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Linked need", "value": obj.material_need.reference},
        {"label": "SAP PR number", "value": obj.sap_pr_number or "Reference pending"},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Decision notes", "value": obj.decision_notes or "—"},
        {"label": "Created by", "value": obj.created_by.username},
        {"label": "Created", "value": obj.created_at.strftime("%Y-%m-%d %H:%M")},
    ]
    ctx["chain"] = [
        {"module_key": "needs", "reference": obj.material_need.reference}
    ]
    role_slugs = role_slugs_for_user(request.user)

    # ODM decision form inline
    if "odm" in role_slugs and obj.status == PurchaseRequest.Status.PENDING_ODM:
        if request.method == "POST" and "odm_decision" in request.POST:
            form = ODMDecisionForm(request.POST)
            if form.is_valid():
                new_status = form.cleaned_data["decision"]
                old = obj.status
                obj.status = new_status
                obj.decision_notes = form.cleaned_data["decision_notes"]
                obj.decided_by = request.user
                obj.decided_at = timezone.now()
                obj.save()
                _audit(request.user, "requests", obj.reference,
                       "ODM decision", old, new_status,
                       form.cleaned_data["decision_notes"])
                return redirect("need_detail", module="requests", reference=reference)
        else:
            form = ODMDecisionForm()
        ctx["odm_form"] = form
        ctx["actions"] = []
        ctx["action_message"] = ""
    elif obj.status == PurchaseRequest.Status.APPROVED:
        ctx["action_message"] = "This request is approved and queued for sourcing."
    elif obj.status in (PurchaseRequest.Status.REJECTED,):
        ctx["action_message"] = "This request was rejected and is now closed."
    else:
        ctx["action_message"] = "No actions available in the current status."
    return render(request, "operations/need_detail.html", ctx)


# --- Stage 4 detail: Quotation ---
def _detail_quotation(request, reference, permitted_module, ctx):
    obj = get_object_or_404(Quotation, reference=reference)
    ctx["status"] = "Selected" if obj.is_selected else "Not selected"
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Supplier", "value": str(obj.supplier)},
        {"label": "Unit price", "value": str(obj.unit_price)},
        {"label": "Total amount", "value": str(obj.total_amount)},
        {"label": "Lead time (days)", "value": str(obj.lead_time_days) if obj.lead_time_days else "—"},
        {"label": "Payment terms", "value": obj.payment_terms or "—"},
        {"label": "Warranty", "value": obj.warranty or "—"},
        {"label": "Score", "value": str(obj.score) if obj.score else "—"},
        {"label": "Selected", "value": "Yes" if obj.is_selected else "No"},
        {"label": "Notes", "value": obj.notes or "—"},
    ]
    ctx["chain"] = [{"module_key": "requests", "reference": obj.purchase_request.reference}]
    ctx["action_message"] = "Quotation records are read-only."
    return render(request, "operations/need_detail.html", ctx)


# --- Stage 5 detail: Purchase Order ---
def _detail_po(request, reference, permitted_module, ctx):
    obj = get_object_or_404(PurchaseOrder, reference=reference)
    ctx["status"] = obj.get_status_display()
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Supplier", "value": str(obj.supplier)},
        {"label": "SAP PO number", "value": obj.sap_po_number or "Pending"},
        {"label": "Total amount", "value": str(obj.total_amount)},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Created by", "value": obj.created_by.username},
        {"label": "Reviewed by", "value": obj.reviewed_by.username if obj.reviewed_by else "—"},
        {"label": "Approved by", "value": obj.approved_by.username if obj.approved_by else "—"},
    ]
    ctx["chain"] = [{"module_key": "requests", "reference": obj.purchase_request.reference}]
    role_slugs = role_slugs_for_user(request.user)

    if "procurement-site-lead" in role_slugs and obj.status == PurchaseOrder.Status.SITE_REVIEW:
        if request.method == "POST" and "site_review" in request.POST:
            form = POReviewForm(request.POST)
            if form.is_valid():
                old = obj.status
                if form.cleaned_data["decision"] == "endorse":
                    obj.status = PurchaseOrder.Status.STRATEGIC_APPROVAL
                    obj.reviewed_by = request.user
                    obj.reviewed_at = timezone.now()
                else:
                    obj.status = PurchaseOrder.Status.DRAFT
                obj.save()
                _audit(request.user, "orders", obj.reference,
                       "Site Lead review", old, obj.status, form.cleaned_data.get("notes", ""))
                return redirect("need_detail", module="orders", reference=reference)
        else:
            form = POReviewForm()
        ctx["site_review_form"] = form

    elif "procurement-strategic-lead" in role_slugs and obj.status == PurchaseOrder.Status.STRATEGIC_APPROVAL:
        if request.method == "POST" and "strategic_approval" in request.POST:
            form = POApprovalForm(request.POST)
            if form.is_valid():
                old = obj.status
                obj.status = form.cleaned_data["decision"]
                obj.approved_by = request.user
                obj.approved_at = timezone.now()
                obj.save()
                _audit(request.user, "orders", obj.reference,
                       "Strategic Lead decision", old, obj.status, form.cleaned_data.get("notes", ""))
                return redirect("need_detail", module="orders", reference=reference)
        else:
            form = POApprovalForm()
        ctx["strategic_approval_form"] = form
    else:
        ctx["action_message"] = "No actions available in the current status for your role."
    return render(request, "operations/need_detail.html", ctx)


# --- Stage 6 detail: Delivery ---
def _detail_delivery(request, reference, permitted_module, ctx):
    obj = get_object_or_404(Delivery, reference=reference)
    ctx["status"] = "Received"
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Purchase order", "value": obj.purchase_order.reference},
        {"label": "Quantity received", "value": str(obj.quantity_received)},
        {"label": "Delivery date", "value": str(obj.delivery_date)},
        {"label": "GR number", "value": obj.sap_gr_number or "—"},
        {"label": "Remarks", "value": obj.remarks or "—"},
        {"label": "Received by", "value": obj.received_by.username},
    ]
    ctx["chain"] = [{"module_key": "orders", "reference": obj.purchase_order.reference}]
    ctx["action_message"] = "Delivery records are read-only after recording."
    return render(request, "operations/need_detail.html", ctx)


# --- Stage 8 detail: Issue Slip ---
def _detail_issue(request, reference, permitted_module, ctx):
    obj = get_object_or_404(IssueSlip, reference=reference)
    ctx["status"] = obj.get_status_display()
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Material", "value": str(obj.material)},
        {"label": "Quantity issued", "value": str(obj.quantity_issued)},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Issued by", "value": obj.issued_by.username},
        {"label": "Issued at", "value": obj.issued_at.strftime("%Y-%m-%d %H:%M")},
        {"label": "Acknowledged by", "value": obj.acknowledged_by.username if obj.acknowledged_by else "Pending"},
    ]
    if obj.material_need:
        ctx["chain"] = [{"module_key": "needs", "reference": obj.material_need.reference}]

    role_slugs = role_slugs_for_user(request.user)
    if "enduser-maintenance-lead" in role_slugs and obj.status == IssueSlip.Status.ISSUED:
        if request.method == "POST" and "acknowledge" in request.POST:
            form = AcknowledgeIssueForm(request.POST)
            if form.is_valid():
                obj.acknowledged_by = request.user
                obj.acknowledged_at = timezone.now()
                obj.status = IssueSlip.Status.ACKNOWLEDGED
                if obj.material_need:
                    obj.material_need.status = MaterialNeed.Status.ISSUED
                    obj.material_need.save()
                remark = form.cleaned_data.get("remark", "")
                obj.save()
                _audit(request.user, "issues", obj.reference,
                       "End user acknowledged", IssueSlip.Status.ISSUED,
                       IssueSlip.Status.ACKNOWLEDGED, remark)
                return redirect("need_detail", module="issues", reference=reference)
        else:
            form = AcknowledgeIssueForm()
        ctx["acknowledge_form"] = form
    else:
        ctx["action_message"] = "No actions available for this record."
    return render(request, "operations/need_detail.html", ctx)


# --- Stage 7 detail: Invoice ---
def _detail_invoice(request, reference, permitted_module, ctx):
    obj = get_object_or_404(Invoice, reference=reference)
    ctx["status"] = obj.get_status_display()
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Invoice number", "value": obj.invoice_number},
        {"label": "Amount", "value": str(obj.amount)},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Purchase order", "value": obj.purchase_order.reference},
        {"label": "Logged by", "value": obj.logged_by.username},
        {"label": "Handed off by", "value": obj.handed_off_by.username if obj.handed_off_by else "—"},
        {"label": "Reviewed by", "value": obj.reviewed_by.username if obj.reviewed_by else "—"},
    ]
    ctx["chain"] = [{"module_key": "orders", "reference": obj.purchase_order.reference}]
    role_slugs = role_slugs_for_user(request.user)

    if "dct" in role_slugs and obj.status == Invoice.Status.LOGGED:
        ctx["actions"] = [{"url": f"?handoff=1", "label": "Hand off to Accounting"}]
        if request.GET.get("handoff") == "1":
            obj.status = Invoice.Status.HANDED_OFF
            obj.handed_off_by = request.user
            obj.handed_off_at = timezone.now()
            obj.save()
            _audit(request.user, "invoices", obj.reference,
                   "Handed off to Accounting",
                   Invoice.Status.LOGGED, Invoice.Status.HANDED_OFF)
            return redirect("need_detail", module="invoices", reference=reference)

    elif "accounting-finance" in role_slugs and obj.status == Invoice.Status.HANDED_OFF:
        if request.method == "POST" and "accounting_review" in request.POST:
            form = AccountingReviewForm(request.POST)
            if form.is_valid():
                old = obj.status
                obj.status = form.cleaned_data["outcome"]
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()
                obj.remarks = form.cleaned_data.get("remarks", "")
                obj.save()
                _audit(request.user, "invoices", obj.reference,
                       "Accounting review", old, obj.status, obj.remarks)
                return redirect("need_detail", module="invoices", reference=reference)
        else:
            form = AccountingReviewForm()
        ctx["accounting_review_form"] = form
    else:
        ctx["action_message"] = "No actions available for this record in its current status."
    return render(request, "operations/need_detail.html", ctx)


# ---------------------------------------------------------------------------
# Form page — creation forms by module
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET", "POST"])
def form_page(request, module):
    module_definition = next((e for e in MODULES if e["key"] == module), None)
    if module_definition is None:
        raise Http404("Unknown module.")

    permitted_module, nav_modules = _base(request, module)
    if permitted_module is None or permitted_module["access"] != "act":
        return render_access_denied(request)

    # dispatch to the right creation handler
    if module == "needs":
        return _create_need(request, permitted_module, nav_modules)
    if module == "requests":
        return _create_pr(request, permitted_module, nav_modules)
    if module == "quotations":
        return _create_quotation(request, permitted_module, nav_modules)
    if module == "orders":
        return _create_po(request, permitted_module, nav_modules)
    if module == "deliveries":
        return _create_delivery(request, permitted_module, nav_modules)
    if module == "issues":
        return _create_issue(request, permitted_module, nav_modules)
    if module == "invoices":
        return _create_invoice(request, permitted_module, nav_modules)

    # fallback demo form
    form = DemonstrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        form.is_valid()
    return _render_form(request, permitted_module, nav_modules, form)


def _render_form(request, permitted_module, nav_modules, form, extra_ctx=None):
    ctx = {
        "module": permitted_module,
        "form": form,
        "cancel_url": permitted_module["url"],
        "role": _role_context(request.user),
        "crumb_parent": permitted_module["label"],
        "crumb_current": "New record",
        "nav_modules": nav_modules,
        "active_module": permitted_module["key"],
    }
    if extra_ctx:
        ctx.update(extra_ctx)
    return render(request, "operations/form_page.html", ctx)


# --- Stage 1: create MaterialNeed ---
def _create_need(request, permitted_module, nav_modules):
    form = MaterialNeedForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.reference = _make_ref("MR")
        obj.created_by = request.user
        obj.status = MaterialNeed.Status.OPEN
        obj.save()
        _audit(request.user, "needs", obj.reference, "Need created", "", MaterialNeed.Status.OPEN)
        return redirect("need_detail", module="needs", reference=obj.reference)
    return _render_form(request, permitted_module, nav_modules, form)


# --- Stage 2: create PurchaseRequest from an approved need ---
def _create_pr(request, permitted_module, nav_modules):
    need_ref = request.GET.get("need")
    need = None
    if need_ref:
        need = get_object_or_404(MaterialNeed, reference=need_ref, status=MaterialNeed.Status.OPEN)
    form = PurchaseRequestForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        linked_need_ref = request.POST.get("linked_need")
        linked_need = get_object_or_404(MaterialNeed, reference=linked_need_ref)
        obj = form.save(commit=False)
        obj.reference = _make_ref("PR")
        obj.material_need = linked_need
        obj.created_by = request.user
        obj.status = PurchaseRequest.Status.PENDING_ODM
        obj.save()
        linked_need.status = MaterialNeed.Status.CONVERTED
        linked_need.save()
        _audit(request.user, "requests", obj.reference, "PR created",
               "", PurchaseRequest.Status.PENDING_ODM)
        return redirect("need_detail", module="requests", reference=obj.reference)
    open_needs = MaterialNeed.objects.filter(status=MaterialNeed.Status.OPEN)
    return _render_form(request, permitted_module, nav_modules, form,
                        {"open_needs": open_needs, "preselected_need": need})


# --- Stage 4: create Quotation ---
def _create_quotation(request, permitted_module, nav_modules):
    pr_ref = request.GET.get("pr")
    pr = None
    if pr_ref:
        pr = get_object_or_404(PurchaseRequest, reference=pr_ref,
                               status=PurchaseRequest.Status.APPROVED)
    form = QuotationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        pr_ref_post = request.POST.get("linked_pr")
        linked_pr = get_object_or_404(PurchaseRequest, reference=pr_ref_post)
        obj = form.save(commit=False)
        obj.reference = _make_ref("QT")
        obj.purchase_request = linked_pr
        obj.created_by = request.user
        obj.save()
        _audit(request.user, "quotations", obj.reference, "Quotation recorded")
        return redirect("need_detail", module="quotations", reference=obj.reference)
    approved_prs = PurchaseRequest.objects.filter(status=PurchaseRequest.Status.APPROVED)
    return _render_form(request, permitted_module, nav_modules, form,
                        {"approved_prs": approved_prs, "preselected_pr": pr})


# --- Stage 5: create PurchaseOrder ---
def _create_po(request, permitted_module, nav_modules):
    pr_ref = request.GET.get("pr")
    pr = None
    if pr_ref:
        pr = get_object_or_404(PurchaseRequest, reference=pr_ref,
                               status=PurchaseRequest.Status.APPROVED)
    form = PurchaseOrderForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        pr_ref_post = request.POST.get("linked_pr")
        qt_ref_post = request.POST.get("linked_quotation")
        linked_pr = get_object_or_404(PurchaseRequest, reference=pr_ref_post)
        linked_qt = Quotation.objects.filter(reference=qt_ref_post).first()
        obj = form.save(commit=False)
        obj.reference = _make_ref("PO")
        obj.purchase_request = linked_pr
        obj.created_by = request.user
        obj.status = PurchaseOrder.Status.SITE_REVIEW
        if linked_qt:
            obj.quotation = linked_qt
            obj.supplier = linked_qt.supplier
            linked_qt.is_selected = True
            linked_qt.save()
        obj.save()
        _audit(request.user, "orders", obj.reference, "PO created",
               "", PurchaseOrder.Status.SITE_REVIEW)
        return redirect("need_detail", module="orders", reference=obj.reference)
    approved_prs = PurchaseRequest.objects.filter(status=PurchaseRequest.Status.APPROVED)
    return _render_form(request, permitted_module, nav_modules, form,
                        {"approved_prs": approved_prs, "preselected_pr": pr})


# --- Stage 6: create Delivery ---
def _create_delivery(request, permitted_module, nav_modules):
    po_ref = request.GET.get("po")
    po = None
    if po_ref:
        po = get_object_or_404(PurchaseOrder, reference=po_ref,
                               status=PurchaseOrder.Status.APPROVED)
    form = DeliveryForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        po_ref_post = request.POST.get("linked_po")
        linked_po = get_object_or_404(PurchaseOrder, reference=po_ref_post)
        obj = form.save(commit=False)
        obj.reference = _make_ref("DR")
        obj.purchase_order = linked_po
        obj.received_by = request.user
        obj.save()
        # update stock
        material = linked_po.purchase_request.material_need.material
        material.stock_on_hand += obj.quantity_received
        material.save()
        _audit(request.user, "deliveries", obj.reference, "Delivery recorded",
               details=f"GR: {obj.sap_gr_number}")
        return redirect("need_detail", module="deliveries", reference=obj.reference)
    approved_pos = PurchaseOrder.objects.filter(status=PurchaseOrder.Status.APPROVED)
    return _render_form(request, permitted_module, nav_modules, form,
                        {"approved_pos": approved_pos, "preselected_po": po})


# --- Stage 7: create Invoice ---
def _create_invoice(request, permitted_module, nav_modules):
    po_ref = request.GET.get("po")
    po = None
    if po_ref:
        po = get_object_or_404(PurchaseOrder, reference=po_ref)
    form = InvoiceForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        po_ref_post = request.POST.get("linked_po")
        linked_po = get_object_or_404(PurchaseOrder, reference=po_ref_post)
        obj = form.save(commit=False)
        obj.reference = _make_ref("INV")
        obj.purchase_order = linked_po
        obj.logged_by = request.user
        obj.status = Invoice.Status.LOGGED
        obj.save()
        _audit(request.user, "invoices", obj.reference, "Invoice logged",
               "", Invoice.Status.LOGGED)
        return redirect("need_detail", module="invoices", reference=obj.reference)
    approved_pos = PurchaseOrder.objects.filter(status=PurchaseOrder.Status.APPROVED)
    return _render_form(request, permitted_module, nav_modules, form,
                        {"approved_pos": approved_pos, "preselected_po": po})


# --- Stage 8: create IssueSlip ---
def _create_issue(request, permitted_module, nav_modules):
    form = IssueSlipForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        material = form.cleaned_data["material"]
        qty = form.cleaned_data["quantity_issued"]
        if material.stock_on_hand < qty:
            form.add_error("quantity_issued",
                           f"Not enough stock. On hand: {material.stock_on_hand} {material.unit}.")
        else:
            obj = form.save(commit=False)
            obj.reference = _make_ref("IS")
            obj.issued_by = request.user
            obj.status = IssueSlip.Status.ISSUED
            obj.save()
            material.stock_on_hand -= qty
            material.save()
            _audit(request.user, "issues", obj.reference, "Issue slip created",
                   "", IssueSlip.Status.ISSUED)
            return redirect("need_detail", module="issues", reference=obj.reference)
    return _render_form(request, permitted_module, nav_modules, form)
