from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods

from accounts.roles import role_by_slug
from accounts.views import render_access_denied

from . import services
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
    QuotationSelectionForm,
    StockAdjustmentForm,
)
from .models import (
    Delivery,
    Invoice,
    IssueSlip,
    Material,
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
from .policies import (
    can_acknowledge_issue,
    can_create_module,
    has_capability,
    module_access_for_user,
    scope_queryset,
    scoped_model_queryset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role_context(user):
    role_slugs = role_slugs_for_user(user)
    if not role_slugs:
        return None
    return {"label": ", ".join(ROLE_LABELS[slug] for slug in role_slugs)}


def _base(request, module_key):
    """Return (permitted_module, nav_modules) or (None, nav_modules)."""
    nav_modules = modules_for_user(request.user)
    permitted = next((m for m in nav_modules if m["key"] == module_key), None)
    return permitted, nav_modules


def _module_definition_or_404(module):
    definition = next((e for e in MODULES if e["key"] == module), None)
    if definition is None:
        raise Http404("Unknown module.")
    return definition


def _get_scoped_or_404(user, module, reference):
    queryset = scoped_model_queryset(user, module)
    lookup = "code" if module == "stock" else "reference"
    return get_object_or_404(queryset, **{lookup: reference})


def _chain_links(user, links):
    """Only expose linked records the user may actually open."""

    visible = []
    for module_key, reference in links:
        if not reference or module_access_for_user(user, module_key) is None:
            continue
        lookup = "code" if module_key == "stock" else "reference"
        if scoped_model_queryset(user, module_key).filter(
            **{lookup: reference}
        ).exists():
            visible.append({"module_key": module_key, "reference": reference})
    return visible


def _form_error_message(form):
    parts = []
    for field_name, errors in form.errors.items():
        if field_name == "__all__":
            label = ""
        else:
            label = form.fields[field_name].label if field_name in form.fields else ""
        for error in errors:
            parts.append(f"{label}: {error}" if label else str(error))
    return "; ".join(parts) or "The submitted values are not valid."


def _action_form(*, form, action_url, submit_label, title, description=""):
    return {
        "form": form,
        "action_url": action_url,
        "submit_label": submit_label,
        "title": title,
        "description": description,
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def _awaiting_count(user, role_slugs):
    total = 0
    if "pr-creator" in role_slugs:
        total += scope_queryset(
            user, "needs", MaterialNeed.objects.filter(status=MaterialNeed.Status.OPEN)
        ).count()
    if "odm" in role_slugs:
        total += PurchaseRequest.objects.filter(
            status=PurchaseRequest.Status.PENDING_ODM
        ).count()
    if "procurement-specialist" in role_slugs:
        total += PurchaseRequest.objects.filter(
            status=PurchaseRequest.Status.APPROVED,
            purchase_orders__isnull=True,
        ).count()
    if "procurement-site-lead" in role_slugs:
        total += PurchaseOrder.objects.filter(
            status=PurchaseOrder.Status.SITE_REVIEW
        ).count()
    if "procurement-strategic-lead" in role_slugs:
        total += PurchaseOrder.objects.filter(
            status=PurchaseOrder.Status.STRATEGIC_APPROVAL
        ).count()
    if "sic-stockroom-gr-creator" in role_slugs:
        total += PurchaseOrder.objects.filter(
            status__in=[
                PurchaseOrder.Status.APPROVED,
                PurchaseOrder.Status.PARTIALLY_DELIVERED,
            ]
        ).count()
    if "dct" in role_slugs:
        total += Invoice.objects.filter(status=Invoice.Status.LOGGED).count()
    if "accounting-finance" in role_slugs:
        total += Invoice.objects.filter(status=Invoice.Status.HANDED_OFF).count()
    if "enduser-maintenance-lead" in role_slugs:
        total += scope_queryset(
            user,
            "issues",
            IssueSlip.objects.filter(status=IssueSlip.Status.ISSUED),
        ).count()
    return total


def _build_queue(user, role_slugs):
    queue = []

    def add(module, queryset, subtitle):
        for item in queryset[:5]:
            reference = item.reference if hasattr(item, "reference") else item.code
            if module and module_access_for_user(user, module):
                queue.append({"title": reference, "subtitle": subtitle})

    if "pr-creator" in role_slugs:
        add(
            "needs",
            scope_queryset(
                user,
                "needs",
                MaterialNeed.objects.filter(status=MaterialNeed.Status.OPEN),
            ),
            "Material need available for request preparation",
        )
    if "odm" in role_slugs:
        add(
            "requests",
            PurchaseRequest.objects.filter(status=PurchaseRequest.Status.PENDING_ODM),
            "Purchase request awaiting your decision",
        )
    if "procurement-specialist" in role_slugs:
        add(
            "requests",
            PurchaseRequest.objects.filter(
                status=PurchaseRequest.Status.APPROVED,
                purchase_orders__isnull=True,
            ),
            "Approved request ready for quotation / order",
        )
    if "procurement-site-lead" in role_slugs:
        add(
            "orders",
            PurchaseOrder.objects.filter(status=PurchaseOrder.Status.SITE_REVIEW),
            "Purchase order awaiting your first review",
        )
    if "procurement-strategic-lead" in role_slugs:
        add(
            "orders",
            PurchaseOrder.objects.filter(status=PurchaseOrder.Status.STRATEGIC_APPROVAL),
            "Purchase order awaiting your final approval",
        )
    if "sic-stockroom-gr-creator" in role_slugs:
        add(
            "orders",
            PurchaseOrder.objects.filter(
                status__in=[
                    PurchaseOrder.Status.APPROVED,
                    PurchaseOrder.Status.PARTIALLY_DELIVERED,
                ]
            ),
            "Approved order awaiting a delivery record",
        )
    if "dct" in role_slugs:
        add(
            "invoices",
            Invoice.objects.filter(status=Invoice.Status.LOGGED),
            "Invoice awaiting handoff to Accounting",
        )
    if "accounting-finance" in role_slugs:
        add(
            "invoices",
            Invoice.objects.filter(status=Invoice.Status.HANDED_OFF),
            "Invoice awaiting your review",
        )
    if "enduser-maintenance-lead" in role_slugs:
        add(
            "issues",
            scope_queryset(
                user,
                "issues",
                IssueSlip.objects.filter(status=IssueSlip.Status.ISSUED),
            ),
            "Issue slip awaiting your acknowledgement",
        )
    return queue[:10]


@login_required
def dashboard(request):
    modules = modules_for_user(request.user)
    role_slugs = role_slugs_for_user(request.user)

    if request.user.is_superuser:
        return redirect("admin:index")
    if "system-administrator" in role_slugs:
        return redirect("system_admin_dashboard")
    if not modules:
        return render_access_denied(request)

    accessible = {module["key"] for module in modules}
    role = None
    description = None
    if role_slugs:
        role = {"label": ", ".join(ROLE_LABELS[slug] for slug in role_slugs)}
        if len(role_slugs) == 1:
            role_definition = role_by_slug(role_slugs[0])
            if role_definition:
                description = role_definition["purpose"]

    open_needs = None
    if "needs" in accessible:
        open_needs = scope_queryset(
            request.user,
            "needs",
            MaterialNeed.objects.filter(status=MaterialNeed.Status.OPEN),
        ).count()

    delivered = None
    if "deliveries" in accessible:
        delivered = scope_queryset(
            request.user, "deliveries", Delivery.objects.all()
        ).count()

    stock_alerts = None
    if "stock" in accessible:
        stock_alerts = Material.objects.filter(
            stock_on_hand__lte=F("reorder_level")
        ).count()

    metrics = [
        {
            "label": "Open needs",
            "value": open_needs,
            "unit": "records",
            "source": "From material needs" if open_needs is not None else "Not available for your role",
        },
        {
            "label": "Awaiting my action",
            "value": _awaiting_count(request.user, role_slugs),
            "unit": "records",
            "source": "Based on your role",
        },
        {
            "label": "Delivered",
            "value": delivered,
            "unit": "records",
            "source": "From recorded receipts" if delivered is not None else "Not available for your role",
        },
        {
            "label": "Stock alerts",
            "value": stock_alerts,
            "unit": "items",
            "source": "At or below reorder level" if stock_alerts is not None else "Not available for your role",
        },
    ]

    action_module = next((m for m in modules if m["access"] == "act"), None)
    primary_action = (
        {"label": "Open " + action_module["label"], "url": action_module["url"]}
        if action_module
        else {"label": "Dashboard", "url": request.path}
    )

    return render(request, "operations/dashboard.html", {
        "role": role,
        "role_description": description,
        "records_connected": True,
        "metrics": metrics,
        "modules": modules,
        "module_count": len(modules),
        "queue": _build_queue(request.user, role_slugs),
        "status": {"source": "PostgreSQL", "last_sync": "Not applicable - live query"},
        "crumb_parent": "Workspace",
        "crumb_current": "Dashboard",
        "nav_modules": modules,
        "active_module": None,
        "primary_action": primary_action,
    })


# ---------------------------------------------------------------------------
# Records list
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
        {"label": "PR reference"},
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
        {"label": "GR reference"},
        {"label": "Date"},
    ],
    "stock": [
        {"label": "Code", "kind": "reference"},
        {"label": "Material"},
        {"label": "On hand", "kind": "number"},
        {"label": "Unit"},
        {"label": "Reorder level", "kind": "number"},
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


def _rows_for_module(user, module_key):
    if module_key == "needs":
        queryset = scope_queryset(user, module_key, MaterialNeed.objects.all())
        return [
            [
                {"kind": "reference", "value": n.reference},
                {"kind": "text", "value": str(n.material)},
                {"kind": "number", "value": str(n.quantity)},
                {"kind": "text", "value": str(n.needed_by) if n.needed_by else "—"},
                {"kind": "status", "value": n.get_status_display()},
            ]
            for n in queryset.select_related("material")
        ]
    if module_key == "requests":
        queryset = scope_queryset(user, module_key, PurchaseRequest.objects.all())
        return [
            [
                {"kind": "reference", "value": pr.reference},
                {"kind": "reference", "value": pr.material_need.reference},
                {"kind": "text", "value": pr.sap_pr_number or "—"},
                {"kind": "status", "value": pr.get_status_display()},
            ]
            for pr in queryset.select_related("material_need")
        ]
    if module_key == "quotations":
        queryset = scope_queryset(user, module_key, Quotation.objects.all())
        return [
            [
                {"kind": "reference", "value": q.reference},
                {"kind": "text", "value": str(q.supplier)},
                {"kind": "number", "value": str(q.total_amount)},
                {"kind": "text", "value": "Yes" if q.is_selected else "No"},
            ]
            for q in queryset.select_related("supplier")
        ]
    if module_key == "orders":
        queryset = scope_queryset(user, module_key, PurchaseOrder.objects.all())
        return [
            [
                {"kind": "reference", "value": po.reference},
                {"kind": "text", "value": str(po.supplier)},
                {"kind": "number", "value": str(po.total_amount)},
                {"kind": "status", "value": po.get_status_display()},
            ]
            for po in queryset.select_related("supplier")
        ]
    if module_key == "deliveries":
        queryset = scope_queryset(user, module_key, Delivery.objects.all())
        return [
            [
                {"kind": "reference", "value": d.reference},
                {"kind": "reference", "value": d.purchase_order.reference},
                {"kind": "number", "value": str(d.quantity_received)},
                {"kind": "text", "value": d.sap_gr_number or "—"},
                {"kind": "text", "value": str(d.delivery_date)},
            ]
            for d in queryset.select_related("purchase_order")
        ]
    if module_key == "stock":
        queryset = scope_queryset(user, module_key, Material.objects.all())
        return [
            [
                {"kind": "reference", "value": m.code},
                {"kind": "text", "value": m.name},
                {"kind": "number", "value": str(m.stock_on_hand)},
                {"kind": "text", "value": m.unit},
                {"kind": "number", "value": str(m.reorder_level)},
            ]
            for m in queryset
        ]
    if module_key == "issues":
        queryset = scope_queryset(user, module_key, IssueSlip.objects.all())
        return [
            [
                {"kind": "reference", "value": s.reference},
                {"kind": "text", "value": str(s.material)},
                {"kind": "number", "value": str(s.quantity_issued)},
                {"kind": "status", "value": s.get_status_display()},
            ]
            for s in queryset.select_related("material")
        ]
    if module_key == "invoices":
        queryset = scope_queryset(user, module_key, Invoice.objects.all())
        return [
            [
                {"kind": "reference", "value": i.reference},
                {"kind": "text", "value": i.invoice_number},
                {"kind": "number", "value": str(i.amount)},
                {"kind": "status", "value": i.get_status_display()},
            ]
            for i in queryset
        ]
    return []


@login_required
def records(request, module):
    _module_definition_or_404(module)
    permitted_module, nav_modules = _base(request, module)
    if permitted_module is None:
        return render_access_denied(request)

    rows = _rows_for_module(request.user, module)
    can_create = can_create_module(request.user, module)
    return render(request, "operations/records.html", {
        "module": permitted_module,
        "columns": _MODULE_COLUMNS.get(module, []),
        "rows": rows,
        "record_count": len(rows),
        "records_connected": True,
        "data_source": "PostgreSQL",
        "title": "No records yet",
        "body": "No records are visible for this module.",
        "can_create": can_create,
        "new_url": reverse("form_page", args=[module]) if can_create else "",
        "role": _role_context(request.user),
        "crumb_parent": "Workspace",
        "crumb_current": permitted_module["label"],
        "nav_modules": nav_modules,
        "active_module": module,
    })


# ---------------------------------------------------------------------------
# Record detail
# ---------------------------------------------------------------------------

@login_required
def need_detail(request, module, reference):
    _module_definition_or_404(module)
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
        "action_form": None,
        "ledger": [],
    }

    if module == "needs":
        return _detail_need(request, reference, ctx)
    if module == "requests":
        return _detail_pr(request, reference, ctx)
    if module == "quotations":
        return _detail_quotation(request, reference, ctx)
    if module == "orders":
        return _detail_po(request, reference, ctx)
    if module == "deliveries":
        return _detail_delivery(request, reference, ctx)
    if module == "stock":
        return _detail_stock(request, reference, ctx)
    if module == "issues":
        return _detail_issue(request, reference, ctx)
    if module == "invoices":
        return _detail_invoice(request, reference, ctx)

    raise Http404("Unknown module.")


def _detail_need(request, reference, ctx):
    obj = _get_scoped_or_404(request.user, "needs", reference)
    ctx["status"] = obj.get_status_display()
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Department", "value": str(obj.department)},
        {"label": "Material", "value": str(obj.material)},
        {"label": "SAP material code", "value": obj.sap_material_code or "Non-standard"},
        {"label": "Area / machine", "value": obj.area or "—"},
        {"label": "Description", "value": obj.description or "—"},
        {"label": "Specification", "value": obj.specification or "—"},
        {"label": "Quantity", "value": str(obj.quantity)},
        {"label": "Needed by", "value": str(obj.needed_by) if obj.needed_by else "—"},
        {"label": "Purpose", "value": obj.purpose or "—"},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Raised by", "value": obj.created_by.get_full_name() or obj.created_by.username},
        {"label": "Created", "value": obj.created_at.strftime("%Y-%m-%d %H:%M")},
    ]
    ctx["chain"] = _chain_links(
        request.user,
        [("requests", pr.reference) for pr in obj.purchase_requests.all()],
    )
    ctx["action_message"] = (
        "Needs are read-only after submission. Create a new need for a different requirement."
    )
    return render(request, "operations/need_detail.html", ctx)


def _detail_pr(request, reference, ctx):
    obj = _get_scoped_or_404(request.user, "requests", reference)
    ctx["status"] = obj.get_status_display()
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Linked need", "value": obj.material_need.reference},
        {"label": "PR reference", "value": obj.sap_pr_number or "Not recorded"},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Decision notes", "value": obj.decision_notes or "—"},
        {"label": "Created by", "value": obj.created_by.username},
        {"label": "Decided by", "value": obj.decided_by.username if obj.decided_by else "—"},
        {"label": "Created", "value": obj.created_at.strftime("%Y-%m-%d %H:%M")},
    ]
    ctx["chain"] = _chain_links(
        request.user,
        [("needs", obj.material_need.reference)],
    )

    if has_capability(request.user, "record_pr_decision") and obj.status == PurchaseRequest.Status.PENDING_ODM:
        ctx["action_form"] = _action_form(
            form=ODMDecisionForm(),
            action_url=reverse("request_decide", args=[obj.reference]),
            submit_label="Record decision",
            title="ODM decision",
            description="You may approve, return, or reject this request. Request fields stay read-only.",
        )
    elif obj.status == PurchaseRequest.Status.APPROVED:
        ctx["action_message"] = "This request is approved and queued for sourcing."
    elif obj.status == PurchaseRequest.Status.RETURNED:
        ctx["action_message"] = "This request was returned for correction."
    elif obj.status == PurchaseRequest.Status.REJECTED:
        ctx["action_message"] = "This request was rejected and is closed."
    else:
        ctx["action_message"] = "No actions are available for this record in its current status."
    return render(request, "operations/need_detail.html", ctx)


def _detail_quotation(request, reference, ctx):
    obj = _get_scoped_or_404(request.user, "quotations", reference)
    ctx["status"] = "Selected" if obj.is_selected else "Not selected"
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Purchase request", "value": obj.purchase_request.reference},
        {"label": "Supplier", "value": str(obj.supplier)},
        {"label": "Unit price", "value": str(obj.unit_price)},
        {"label": "Total amount", "value": str(obj.total_amount)},
        {"label": "Lead time (days)", "value": str(obj.lead_time_days) if obj.lead_time_days else "—"},
        {"label": "Payment terms", "value": obj.payment_terms or "—"},
        {"label": "Warranty", "value": obj.warranty or "—"},
        {"label": "Score", "value": str(obj.score) if obj.score is not None else "—"},
        {"label": "Selected", "value": "Yes" if obj.is_selected else "No"},
        {"label": "Selected by", "value": obj.selected_by.username if obj.selected_by else "—"},
        {"label": "Selection notes", "value": obj.selection_notes or "—"},
        {"label": "Notes", "value": obj.notes or "—"},
    ]
    ctx["chain"] = _chain_links(
        request.user,
        [("requests", obj.purchase_request.reference)],
    )

    can_select = (
        has_capability(request.user, "manage_quotations")
        and obj.purchase_request.status == PurchaseRequest.Status.APPROVED
        and not PurchaseOrder.objects.filter(purchase_request=obj.purchase_request).exists()
    )
    if can_select:
        ctx["action_form"] = _action_form(
            form=QuotationSelectionForm(),
            action_url=reverse("quotation_select", args=[obj.reference]),
            submit_label="Select this quotation" if not obj.is_selected else "Update selection notes",
            title="Select the winning quotation",
            description="Only one quotation can be selected for a request. The PO must use it.",
        )
    else:
        ctx["action_message"] = "Quotation records are read-only in the current state."
    return render(request, "operations/need_detail.html", ctx)


def _detail_po(request, reference, ctx):
    obj = _get_scoped_or_404(request.user, "orders", reference)
    ctx["status"] = obj.get_status_display()
    ordered_quantity = obj.purchase_request.material_need.quantity
    delivered_quantity = sum(
        (delivery.quantity_received for delivery in obj.deliveries.all()),
        start=0,
    )
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Purchase request", "value": obj.purchase_request.reference},
        {"label": "Supplier", "value": str(obj.supplier)},
        {"label": "PO reference", "value": obj.sap_po_number or "Not recorded"},
        {"label": "Total amount", "value": str(obj.total_amount)},
        {"label": "Ordered quantity", "value": str(ordered_quantity)},
        {"label": "Delivered quantity", "value": str(delivered_quantity)},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Created by", "value": obj.created_by.username},
        {"label": "Reviewed by", "value": obj.reviewed_by.username if obj.reviewed_by else "—"},
        {"label": "Review notes", "value": obj.review_notes or "—"},
        {"label": "Approved by", "value": obj.approved_by.username if obj.approved_by else "—"},
        {"label": "Approval notes", "value": obj.approval_notes or "—"},
    ]
    ctx["chain"] = _chain_links(
        request.user,
        [
            ("requests", obj.purchase_request.reference),
            ("quotations", obj.quotation.reference if obj.quotation else ""),
        ],
    )

    if has_capability(request.user, "review_po") and obj.status == PurchaseOrder.Status.SITE_REVIEW:
        ctx["action_form"] = _action_form(
            form=POReviewForm(),
            action_url=reverse("order_review", args=[obj.reference]),
            submit_label="Record first review",
            title="First-stage review (Site Lead)",
            description="Endorsing sends the order to the Strategic Lead. Returning sends it back to the specialist.",
        )
    elif has_capability(request.user, "approve_po") and obj.status == PurchaseOrder.Status.STRATEGIC_APPROVAL:
        ctx["action_form"] = _action_form(
            form=POApprovalForm(),
            action_url=reverse("order_approve", args=[obj.reference]),
            submit_label="Record final decision",
            title="Final approval (Strategic Lead)",
            description="Approval is only available after the first-stage review.",
        )
    elif has_capability(request.user, "record_po_reference") and obj.status == PurchaseOrder.Status.DRAFT:
        ctx["action_form"] = _action_form(
            form=None,
            action_url=reverse("order_resubmit", args=[obj.reference]),
            submit_label="Resubmit for first review",
            title="Returned order",
            description="This order was returned by the Site Lead. Resubmit it for a new first review.",
        )
    else:
        ctx["action_message"] = "No actions are available for this record in its current status for your role."
    return render(request, "operations/need_detail.html", ctx)


def _detail_delivery(request, reference, ctx):
    obj = _get_scoped_or_404(request.user, "deliveries", reference)
    ctx["status"] = "Received"
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Purchase order", "value": obj.purchase_order.reference},
        {"label": "Quantity received", "value": str(obj.quantity_received)},
        {"label": "Delivery date", "value": str(obj.delivery_date)},
        {"label": "GR reference", "value": obj.sap_gr_number or "Not recorded"},
        {"label": "Remarks", "value": obj.remarks or "—"},
        {"label": "Received by", "value": obj.received_by.username},
    ]
    ctx["chain"] = _chain_links(
        request.user,
        [("orders", obj.purchase_order.reference)],
    )
    ctx["action_message"] = "Delivery records are read-only after recording."
    return render(request, "operations/need_detail.html", ctx)


def _detail_stock(request, reference, ctx):
    obj = _get_scoped_or_404(request.user, "stock", reference)
    ctx["status"] = "Stock item"
    ctx["fields"] = [
        {"label": "Code", "value": obj.code},
        {"label": "Material", "value": obj.name},
        {"label": "Unit", "value": obj.unit},
        {"label": "Stock on hand", "value": str(obj.stock_on_hand)},
        {"label": "Reorder level", "value": str(obj.reorder_level)},
    ]
    movements = obj.stock_movements.select_related("actor", "delivery", "issue")[:25]
    ctx["ledger"] = [
        {
            "created_at": movement.created_at,
            "actor": movement.actor.username if movement.actor else "System",
            "delta": f"{movement.delta:+}",
            "reason": movement.get_reason_display(),
            "note": movement.note or "—",
            "source": (
                movement.delivery.reference
                if movement.delivery
                else movement.issue.reference
                if movement.issue
                else "—"
            ),
        }
        for movement in movements
    ]
    ctx["action_message"] = "Stock changes are recorded through controlled stock transactions."
    return render(request, "operations/need_detail.html", ctx)


def _detail_issue(request, reference, ctx):
    obj = _get_scoped_or_404(request.user, "issues", reference)
    ctx["status"] = obj.get_status_display()
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Material", "value": str(obj.material)},
        {"label": "Quantity issued", "value": str(obj.quantity_issued)},
        {"label": "Department", "value": str(obj.department) if obj.department else "—"},
        {"label": "Linked need", "value": obj.material_need.reference if obj.material_need else "—"},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Issued by", "value": obj.issued_by.username},
        {"label": "Issued at", "value": obj.issued_at.strftime("%Y-%m-%d %H:%M")},
        {"label": "Acknowledged by", "value": obj.acknowledged_by.username if obj.acknowledged_by else "Pending"},
        {"label": "Condition notes", "value": obj.condition_notes or "—"},
    ]
    links = []
    if obj.material_need:
        links.append(("needs", obj.material_need.reference))
    ctx["chain"] = _chain_links(request.user, links)

    if can_acknowledge_issue(request.user, obj) and obj.status == IssueSlip.Status.ISSUED:
        ctx["action_form"] = _action_form(
            form=AcknowledgeIssueForm(),
            action_url=reverse("issue_acknowledge", args=[obj.reference]),
            submit_label="Record acknowledgement",
            title="Acknowledge or dispute this issue",
            description="A dispute records a condition problem and keeps the event in the audit trail.",
        )
    elif obj.status == IssueSlip.Status.ACKNOWLEDGED:
        ctx["action_message"] = "This issue has been acknowledged by the requester."
    elif obj.status == IssueSlip.Status.DISPUTED:
        ctx["action_message"] = "This issue is disputed. The condition note is recorded."
    else:
        ctx["action_message"] = "No actions are available for this record."
    return render(request, "operations/need_detail.html", ctx)


def _detail_invoice(request, reference, ctx):
    obj = _get_scoped_or_404(request.user, "invoices", reference)
    ctx["status"] = obj.get_status_display()
    ctx["fields"] = [
        {"label": "Reference", "value": obj.reference},
        {"label": "Invoice number", "value": obj.invoice_number},
        {"label": "Amount", "value": str(obj.amount)},
        {"label": "Status", "value": obj.get_status_display()},
        {"label": "Purchase order", "value": obj.purchase_order.reference},
        {"label": "Delivery / GR", "value": obj.delivery.reference if obj.delivery else "—"},
        {"label": "Logged by", "value": obj.logged_by.username},
        {"label": "Handed off by", "value": obj.handed_off_by.username if obj.handed_off_by else "—"},
        {"label": "Reviewed by", "value": obj.reviewed_by.username if obj.reviewed_by else "—"},
        {"label": "DCT remarks", "value": obj.remarks or "—"},
        {"label": "Review remarks", "value": obj.review_remarks or "—"},
    ]
    links = [("orders", obj.purchase_order.reference)]
    if obj.delivery:
        links.append(("deliveries", obj.delivery.reference))
    ctx["chain"] = _chain_links(request.user, links)

    if has_capability(request.user, "record_handoff") and obj.status == Invoice.Status.LOGGED:
        ctx["action_form"] = _action_form(
            form=None,
            action_url=reverse("invoice_handoff", args=[obj.reference]),
            submit_label="Hand off to Accounting",
            title="Invoice handoff",
            description="This records DCT's handoff. Accounting records the separate review outcome.",
        )
    elif has_capability(request.user, "review_invoice") and obj.status == Invoice.Status.HANDED_OFF:
        ctx["action_form"] = _action_form(
            form=AccountingReviewForm(),
            action_url=reverse("invoice_review", args=[obj.reference]),
            submit_label="Record review outcome",
            title="Accounting review",
            description="Record matched, disputed, on hold, or returned. A typed GR reference is not an SAP verification.",
        )
    else:
        ctx["action_message"] = "No actions are available for this record in its current status for your role."
    return render(request, "operations/need_detail.html", ctx)


# ---------------------------------------------------------------------------
# Form page - creation handlers
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET", "POST"])
def form_page(request, module):
    _module_definition_or_404(module)
    permitted_module, nav_modules = _base(request, module)
    if permitted_module is None or not can_create_module(request.user, module):
        return render_access_denied(request)

    handlers = {
        "needs": _create_need,
        "requests": _create_pr,
        "quotations": _create_quotation,
        "orders": _create_po,
        "deliveries": _create_delivery,
        "stock": _create_stock_adjustment,
        "issues": _create_issue,
        "invoices": _create_invoice,
    }
    handler = handlers.get(module)
    if handler is None:
        form = DemonstrationForm(request.POST if request.method == "POST" else None)
        return _render_form(request, permitted_module, nav_modules, form)
    return handler(request, permitted_module, nav_modules)


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


def _create_need(request, permitted_module, nav_modules):
    initial = {}
    profile = getattr(request.user, "profile", None)
    if profile is not None and profile.department_id:
        initial["department"] = profile.department
    form = MaterialNeedForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            obj = services.create_material_need(
                request.user,
                department=form.cleaned_data["department"],
                material=form.cleaned_data["material"],
                quantity=form.cleaned_data["quantity"],
                area=form.cleaned_data["area"],
                description=form.cleaned_data["description"],
                specification=form.cleaned_data["specification"],
                sap_material_code=form.cleaned_data["sap_material_code"],
                needed_by=form.cleaned_data["needed_by"],
                purpose=form.cleaned_data["purpose"],
            )
        except services.WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Material need submitted.")
            return redirect("need_detail", module="needs", reference=obj.reference)
    return _render_form(request, permitted_module, nav_modules, form)


def _create_pr(request, permitted_module, nav_modules):
    initial = {}
    need_ref = request.GET.get("need")
    if need_ref:
        need = MaterialNeed.objects.filter(
            reference=need_ref, status=MaterialNeed.Status.OPEN
        ).first()
        if need:
            initial["material_need"] = need
    form = PurchaseRequestForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            obj = services.create_purchase_request(
                request.user,
                material_need=form.cleaned_data["material_need"],
                sap_pr_number=form.cleaned_data["sap_pr_number"],
                notes=form.cleaned_data["decision_notes"],
            )
        except services.WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Purchase request prepared.")
            return redirect("need_detail", module="requests", reference=obj.reference)
    return _render_form(request, permitted_module, nav_modules, form)


def _create_quotation(request, permitted_module, nav_modules):
    initial = {}
    pr_ref = request.GET.get("pr")
    if pr_ref:
        purchase_request = PurchaseRequest.objects.filter(
            reference=pr_ref, status=PurchaseRequest.Status.APPROVED
        ).first()
        if purchase_request:
            initial["purchase_request"] = purchase_request
    form = QuotationForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            obj = services.create_quotation(
                request.user,
                purchase_request=form.cleaned_data["purchase_request"],
                supplier=form.cleaned_data["supplier"],
                unit_price=form.cleaned_data["unit_price"],
                total_amount=form.cleaned_data["total_amount"],
                lead_time_days=form.cleaned_data["lead_time_days"],
                payment_terms=form.cleaned_data["payment_terms"],
                warranty=form.cleaned_data["warranty"],
                score=form.cleaned_data["score"],
                notes=form.cleaned_data["notes"],
            )
        except services.WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Quotation recorded.")
            return redirect("need_detail", module="quotations", reference=obj.reference)
    return _render_form(request, permitted_module, nav_modules, form)


def _create_po(request, permitted_module, nav_modules):
    initial = {}
    pr_ref = request.GET.get("pr")
    if pr_ref:
        purchase_request = PurchaseRequest.objects.filter(
            reference=pr_ref, status=PurchaseRequest.Status.APPROVED
        ).first()
        if purchase_request:
            initial["purchase_request"] = purchase_request
    form = PurchaseOrderForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            obj = services.create_purchase_order(
                request.user,
                purchase_request=form.cleaned_data["purchase_request"],
                quotation=form.cleaned_data["quotation"],
                sap_po_number=form.cleaned_data["sap_po_number"],
                total_amount=form.cleaned_data["total_amount"],
            )
        except services.WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Purchase order started and sent for first review.")
            return redirect("need_detail", module="orders", reference=obj.reference)
    return _render_form(request, permitted_module, nav_modules, form)


def _create_delivery(request, permitted_module, nav_modules):
    initial = {}
    po_ref = request.GET.get("po")
    if po_ref:
        purchase_order = PurchaseOrder.objects.filter(
            reference=po_ref,
            status__in=[
                PurchaseOrder.Status.APPROVED,
                PurchaseOrder.Status.PARTIALLY_DELIVERED,
            ],
        ).first()
        if purchase_order:
            initial["purchase_order"] = purchase_order
    form = DeliveryForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            obj = services.record_delivery(
                request.user,
                purchase_order=form.cleaned_data["purchase_order"],
                quantity_received=form.cleaned_data["quantity_received"],
                delivery_date=form.cleaned_data["delivery_date"],
                gr_reference=form.cleaned_data["sap_gr_number"],
                remarks=form.cleaned_data["remarks"],
            )
        except services.WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Delivery recorded. GR reference saved as typed text.")
            return redirect("need_detail", module="deliveries", reference=obj.reference)
    return _render_form(request, permitted_module, nav_modules, form)


def _create_stock_adjustment(request, permitted_module, nav_modules):
    form = StockAdjustmentForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            movement = services.adjust_stock(
                request.user,
                material=form.cleaned_data["material"],
                delta=form.cleaned_data["delta"],
                reason=form.cleaned_data["reason"],
                note=form.cleaned_data["note"],
            )
        except services.WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Stock movement recorded.")
            return redirect(
                "need_detail",
                module="stock",
                reference=movement.material.code,
            )
    return _render_form(request, permitted_module, nav_modules, form)


def _create_issue(request, permitted_module, nav_modules):
    form = IssueSlipForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            obj = services.record_issue(
                request.user,
                material=form.cleaned_data["material"],
                quantity=form.cleaned_data["quantity_issued"],
                department=form.cleaned_data["department"],
                material_need=form.cleaned_data["material_need"],
            )
        except services.WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Issue slip recorded.")
            return redirect("need_detail", module="issues", reference=obj.reference)
    return _render_form(request, permitted_module, nav_modules, form)


def _create_invoice(request, permitted_module, nav_modules):
    initial = {}
    po_ref = request.GET.get("po")
    if po_ref:
        purchase_order = PurchaseOrder.objects.filter(
            reference=po_ref,
            status__in=[
                PurchaseOrder.Status.APPROVED,
                PurchaseOrder.Status.PARTIALLY_DELIVERED,
                PurchaseOrder.Status.DELIVERED,
            ],
        ).first()
        if purchase_order:
            initial["purchase_order"] = purchase_order
    form = InvoiceForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            obj = services.log_invoice(
                request.user,
                purchase_order=form.cleaned_data["purchase_order"],
                delivery=form.cleaned_data["delivery"],
                invoice_number=form.cleaned_data["invoice_number"],
                amount=form.cleaned_data["amount"],
                remarks=form.cleaned_data["remarks"],
            )
        except services.WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Invoice logged.")
            return redirect("need_detail", module="invoices", reference=obj.reference)
    return _render_form(request, permitted_module, nav_modules, form)


# ---------------------------------------------------------------------------
# State-changing action endpoints (POST only)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def request_decide(request, reference):
    if not has_capability(request.user, "record_pr_decision"):
        return render_access_denied(request)
    obj = _get_scoped_or_404(request.user, "requests", reference)
    form = ODMDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect("need_detail", module="requests", reference=reference)
    try:
        services.decide_purchase_request(
            request.user,
            purchase_request=obj,
            decision=form.cleaned_data["decision"],
            notes=form.cleaned_data["decision_notes"],
        )
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "ODM decision recorded.")
    return redirect("need_detail", module="requests", reference=reference)


@login_required
@require_POST
def order_review(request, reference):
    if not has_capability(request.user, "review_po"):
        return render_access_denied(request)
    obj = _get_scoped_or_404(request.user, "orders", reference)
    form = POReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect("need_detail", module="orders", reference=reference)
    try:
        services.review_purchase_order(
            request.user,
            purchase_order=obj,
            decision=form.cleaned_data["decision"],
            notes=form.cleaned_data["notes"],
        )
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "First-stage review recorded.")
    return redirect("need_detail", module="orders", reference=reference)


@login_required
@require_POST
def order_approve(request, reference):
    if not has_capability(request.user, "approve_po"):
        return render_access_denied(request)
    obj = _get_scoped_or_404(request.user, "orders", reference)
    form = POApprovalForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect("need_detail", module="orders", reference=reference)
    try:
        services.approve_purchase_order(
            request.user,
            purchase_order=obj,
            decision=form.cleaned_data["decision"],
            notes=form.cleaned_data["notes"],
        )
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Final approval decision recorded.")
    return redirect("need_detail", module="orders", reference=reference)


@login_required
@require_POST
def order_resubmit(request, reference):
    if not has_capability(request.user, "record_po_reference"):
        return render_access_denied(request)
    obj = _get_scoped_or_404(request.user, "orders", reference)
    try:
        services.resubmit_purchase_order(request.user, purchase_order=obj)
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Order resubmitted for first review.")
    return redirect("need_detail", module="orders", reference=reference)


@login_required
@require_POST
def quotation_select(request, reference):
    if not has_capability(request.user, "manage_quotations"):
        return render_access_denied(request)
    obj = _get_scoped_or_404(request.user, "quotations", reference)
    form = QuotationSelectionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect("need_detail", module="quotations", reference=reference)
    try:
        services.select_quotation(
            request.user,
            quotation=obj,
            notes=form.cleaned_data["notes"],
        )
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Quotation selection recorded.")
    return redirect("need_detail", module="quotations", reference=reference)


@login_required
@require_POST
def issue_acknowledge(request, reference):
    if not has_capability(request.user, "acknowledge_issue"):
        return render_access_denied(request)
    obj = _get_scoped_or_404(request.user, "issues", reference)
    form = AcknowledgeIssueForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect("need_detail", module="issues", reference=reference)
    try:
        services.acknowledge_issue(
            request.user,
            issue=obj,
            decision=form.cleaned_data["decision"],
            remark=form.cleaned_data["remark"],
        )
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Acknowledgement recorded.")
    return redirect("need_detail", module="issues", reference=reference)


@login_required
@require_POST
def invoice_handoff(request, reference):
    if not has_capability(request.user, "record_handoff"):
        return render_access_denied(request)
    obj = _get_scoped_or_404(request.user, "invoices", reference)
    try:
        services.handoff_invoice(request.user, invoice=obj)
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Invoice handed off to Accounting.")
    return redirect("need_detail", module="invoices", reference=reference)


@login_required
@require_POST
def invoice_review(request, reference):
    if not has_capability(request.user, "review_invoice"):
        return render_access_denied(request)
    obj = _get_scoped_or_404(request.user, "invoices", reference)
    form = AccountingReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect("need_detail", module="invoices", reference=reference)
    try:
        services.review_invoice(
            request.user,
            invoice=obj,
            outcome=form.cleaned_data["outcome"],
            remarks=form.cleaned_data["remarks"],
        )
    except services.WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Accounting review recorded.")
    return redirect("need_detail", module="invoices", reference=reference)
