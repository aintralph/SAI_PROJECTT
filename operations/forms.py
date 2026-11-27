from decimal import Decimal

from django import forms

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


def _style(field):
    widget = field.widget
    if isinstance(widget, forms.CheckboxInput):
        widget.attrs["class"] = "checkbox"
    elif isinstance(widget, forms.Textarea):
        widget.attrs["class"] = "input"
        widget.attrs.setdefault("rows", 3)
    else:
        widget.attrs["class"] = "input"


def _style_all(form):
    for field in form.fields.values():
        _style(field)


# ---------------------------------------------------------------------------
# Stage 1 - End User: Material Need
# ---------------------------------------------------------------------------
class MaterialNeedForm(forms.ModelForm):
    class Meta:
        model = MaterialNeed
        fields = [
            "material",
            "department",
            "area",
            "sap_material_code",
            "description",
            "specification",
            "quantity",
            "needed_by",
            "purpose",
        ]
        widgets = {
            "needed_by": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "material": "Material",
            "department": "Department",
            "area": "Area / Machine",
            "sap_material_code": "SAP material code (optional)",
            "description": "Material description (required for non-standard items)",
            "specification": "Specification",
            "quantity": "Quantity needed",
            "needed_by": "Required by",
            "purpose": "Purpose / justification",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["department"].queryset = self.fields[
            "department"
        ].queryset.order_by("name")
        self.fields["material"].queryset = self.fields[
            "material"
        ].queryset.order_by("name")
        self.fields["area"].required = True
        self.fields["description"].required = False
        self.fields["specification"].required = False
        self.fields["sap_material_code"].required = False
        self.fields["needed_by"].required = True
        self.fields["purpose"].required = True
        self.fields["sap_material_code"].help_text = (
            "Leave blank for a non-standard item and describe it below."
        )

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than zero.")
        return quantity

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("sap_material_code") and not cleaned.get("description"):
            self.add_error(
                "description",
                "Describe the material when no SAP material code is supplied.",
            )
        return cleaned


# ---------------------------------------------------------------------------
# Stage 2 - PR Creator: Purchase Request
# ---------------------------------------------------------------------------
class PurchaseRequestForm(forms.ModelForm):
    material_need = forms.ModelChoiceField(
        queryset=MaterialNeed.objects.none(),
        label="Source material need",
        empty_label="-- choose an open need --",
    )

    class Meta:
        model = PurchaseRequest
        fields = ["material_need", "sap_pr_number", "decision_notes"]
        labels = {
            "sap_pr_number": "PR reference (typed manually, optional)",
            "decision_notes": "Notes / remarks",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["material_need"].queryset = MaterialNeed.objects.filter(
            status=MaterialNeed.Status.OPEN
        ).select_related("material", "department").order_by("-created_at")
        self.fields["sap_pr_number"].required = False
        self.fields["sap_pr_number"].help_text = (
            "Enter the request reference from the source system, or leave blank."
        )
        self.fields["decision_notes"].required = False


# ---------------------------------------------------------------------------
# Stage 3 - ODM: PR Decision
# ---------------------------------------------------------------------------
class ODMDecisionForm(forms.Form):
    DECISION_CHOICES = [
        (PurchaseRequest.Status.APPROVED, "Approve"),
        (PurchaseRequest.Status.RETURNED, "Return for correction"),
        (PurchaseRequest.Status.REJECTED, "Reject"),
    ]
    decision = forms.ChoiceField(choices=DECISION_CHOICES, widget=forms.RadioSelect)
    decision_notes = forms.CharField(
        label="Reason / notes (required when returning or rejecting)",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields["decision_notes"])

    def clean(self):
        cleaned = super().clean()
        decision = cleaned.get("decision")
        notes = cleaned.get("decision_notes", "").strip()
        if decision in (
            PurchaseRequest.Status.RETURNED,
            PurchaseRequest.Status.REJECTED,
        ) and not notes:
            raise forms.ValidationError(
                "A reason is required when returning or rejecting a request."
            )
        return cleaned


# ---------------------------------------------------------------------------
# Stage 4 - Specialist: Quotation
# ---------------------------------------------------------------------------
class QuotationForm(forms.ModelForm):
    purchase_request = forms.ModelChoiceField(
        queryset=PurchaseRequest.objects.none(),
        label="Approved purchase request",
        empty_label="-- choose an approved request --",
    )

    class Meta:
        model = Quotation
        fields = [
            "purchase_request",
            "supplier",
            "unit_price",
            "total_amount",
            "lead_time_days",
            "payment_terms",
            "warranty",
            "score",
            "notes",
        ]
        labels = {
            "supplier": "Supplier",
            "unit_price": "Unit price",
            "total_amount": "Total amount",
            "lead_time_days": "Lead time (days)",
            "payment_terms": "Payment terms",
            "warranty": "Warranty",
            "score": "Weighted score (optional)",
            "notes": "Notes",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["purchase_request"].queryset = PurchaseRequest.objects.filter(
            status=PurchaseRequest.Status.APPROVED
        ).select_related("material_need__material").order_by("-created_at")
        self.fields["lead_time_days"].required = False
        self.fields["payment_terms"].required = False
        self.fields["warranty"].required = False
        self.fields["score"].required = False
        self.fields["notes"].required = False

    def clean_unit_price(self):
        value = self.cleaned_data["unit_price"]
        if value < 0:
            raise forms.ValidationError("Unit price cannot be negative.")
        return value

    def clean_total_amount(self):
        value = self.cleaned_data["total_amount"]
        if value < 0:
            raise forms.ValidationError("Total amount cannot be negative.")
        return value


class QuotationSelectionForm(forms.Form):
    notes = forms.CharField(
        label="Selection justification",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields["notes"])


class SelectQuotationForm(forms.Form):
    """Specialist picks the winning quotation before creating the PO."""

    quotation = forms.ModelChoiceField(
        queryset=Quotation.objects.none(),
        label="Select the winning quotation",
        empty_label="-- choose one --",
    )
    notes = forms.CharField(
        label="Selection justification (required if scores are tied)",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, purchase_request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quotation"].queryset = Quotation.objects.filter(
            purchase_request=purchase_request
        )
        _style_all(self)


# ---------------------------------------------------------------------------
# Stage 5 - Specialist: Purchase Order
# ---------------------------------------------------------------------------
class PurchaseOrderForm(forms.ModelForm):
    purchase_request = forms.ModelChoiceField(
        queryset=PurchaseRequest.objects.none(),
        label="Approved purchase request",
        empty_label="-- choose an approved request --",
    )
    quotation = forms.ModelChoiceField(
        queryset=Quotation.objects.none(),
        label="Selected quotation",
        empty_label="-- choose a selected quotation --",
    )
    total_amount = forms.DecimalField(
        label="Total order amount",
        min_value=Decimal("0"),
        required=False,
        max_digits=12,
        decimal_places=2,
    )

    class Meta:
        model = PurchaseOrder
        fields = ["purchase_request", "quotation", "sap_po_number", "total_amount"]
        labels = {
            "sap_po_number": "PO reference (typed manually, optional)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["purchase_request"].queryset = PurchaseRequest.objects.filter(
            status=PurchaseRequest.Status.APPROVED
        ).order_by("-created_at")
        self.fields["quotation"].queryset = Quotation.objects.filter(
            is_selected=True,
            purchase_request__status=PurchaseRequest.Status.APPROVED,
        ).select_related("purchase_request", "supplier").order_by("-created_at")
        self.fields["sap_po_number"].required = False
        self.fields["sap_po_number"].help_text = (
            "Enter the purchase order reference from the source system, or leave blank."
        )

    def clean(self):
        cleaned = super().clean()
        purchase_request = cleaned.get("purchase_request")
        quotation = cleaned.get("quotation")
        if purchase_request and quotation:
            if quotation.purchase_request_id != purchase_request.id:
                self.add_error(
                    "quotation",
                    "The selected quotation does not belong to this request.",
                )
            elif not quotation.is_selected:
                self.add_error("quotation", "Select the winning quotation first.")
            elif not cleaned.get("total_amount"):
                cleaned["total_amount"] = quotation.total_amount
        return cleaned


class POReviewForm(forms.Form):
    """Site Lead endorses or returns the PO."""
    CHOICES = [
        ("endorse", "Endorse (send to Strategic Lead)"),
        ("return", "Return to Specialist"),
    ]
    decision = forms.ChoiceField(choices=CHOICES, widget=forms.RadioSelect)
    notes = forms.CharField(
        label="Notes (required when returning)",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields["notes"])

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "return" and not cleaned.get("notes", "").strip():
            raise forms.ValidationError("A reason is required when returning.")
        return cleaned


class POApprovalForm(forms.Form):
    """Strategic Lead approves or rejects the PO."""
    CHOICES = [
        (PurchaseOrder.Status.APPROVED, "Approve"),
        (PurchaseOrder.Status.REJECTED, "Reject"),
    ]
    decision = forms.ChoiceField(choices=CHOICES, widget=forms.RadioSelect)
    notes = forms.CharField(
        label="Notes (required when rejecting)",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields["notes"])

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("decision") == PurchaseOrder.Status.REJECTED
            and not cleaned.get("notes", "").strip()
        ):
            raise forms.ValidationError("A reason is required when rejecting.")
        return cleaned


# ---------------------------------------------------------------------------
# Stage 6 - SIC: Delivery / Goods Receipt
# ---------------------------------------------------------------------------
class DeliveryForm(forms.ModelForm):
    purchase_order = forms.ModelChoiceField(
        queryset=PurchaseOrder.objects.none(),
        label="Approved purchase order",
        empty_label="-- choose an approved order --",
    )
    sap_gr_number = forms.CharField(
        label="GR reference (manually entered)",
        max_length=50,
        required=True,
        help_text="Type the goods-receipt reference. This does not post to SAP.",
    )

    class Meta:
        model = Delivery
        fields = [
            "purchase_order",
            "delivery_date",
            "quantity_received",
            "sap_gr_number",
            "remarks",
        ]
        widgets = {
            "delivery_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "delivery_date": "Delivery date",
            "quantity_received": "Quantity received",
            "remarks": "Condition / remarks",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["purchase_order"].queryset = PurchaseOrder.objects.filter(
            status__in=[
                PurchaseOrder.Status.APPROVED,
                PurchaseOrder.Status.PARTIALLY_DELIVERED,
            ]
        ).select_related("supplier").order_by("-created_at")
        self.fields["remarks"].required = False

    def clean_quantity_received(self):
        quantity = self.cleaned_data["quantity_received"]
        if quantity <= 0:
            raise forms.ValidationError("Quantity received must be greater than zero.")
        return quantity


# ---------------------------------------------------------------------------
# Stage 7 - DCT: Invoice logging
# ---------------------------------------------------------------------------
class InvoiceForm(forms.ModelForm):
    purchase_order = forms.ModelChoiceField(
        queryset=PurchaseOrder.objects.none(),
        label="Purchase order",
        empty_label="-- choose an approved order --",
    )
    delivery = forms.ModelChoiceField(
        queryset=Delivery.objects.none(),
        label="Delivery / GR record (optional)",
        required=False,
        empty_label="-- no specific delivery --",
    )

    class Meta:
        model = Invoice
        fields = ["purchase_order", "delivery", "invoice_number", "amount", "remarks"]
        labels = {
            "invoice_number": "Supplier invoice number",
            "amount": "Invoice amount",
            "remarks": "Remarks",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["purchase_order"].queryset = PurchaseOrder.objects.filter(
            status__in=[
                PurchaseOrder.Status.APPROVED,
                PurchaseOrder.Status.PARTIALLY_DELIVERED,
                PurchaseOrder.Status.DELIVERED,
            ]
        ).select_related("supplier").order_by("-created_at")
        self.fields["delivery"].queryset = Delivery.objects.select_related(
            "purchase_order"
        ).order_by("-created_at")
        self.fields["remarks"].required = False

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount < 0:
            raise forms.ValidationError("The invoice amount cannot be negative.")
        return amount

    def clean(self):
        cleaned = super().clean()
        purchase_order = cleaned.get("purchase_order")
        delivery = cleaned.get("delivery")
        if purchase_order and delivery and delivery.purchase_order_id != purchase_order.id:
            self.add_error(
                "delivery",
                "The selected delivery does not belong to this purchase order.",
            )
        return cleaned


class AccountingReviewForm(forms.Form):
    """Accounting records one of four outcomes."""
    OUTCOME_CHOICES = [
        (Invoice.Status.MATCHED, "Matched - ordered, received and invoiced agree"),
        (Invoice.Status.DISPUTED, "Disputed - price or quantity differs"),
        (Invoice.Status.ON_HOLD, "On hold - invoice received but goods not yet in"),
        (Invoice.Status.RETURNED, "Returned - sent back to DCT or Procurement"),
    ]
    outcome = forms.ChoiceField(choices=OUTCOME_CHOICES, widget=forms.RadioSelect)
    remarks = forms.CharField(
        label="Remarks (required for disputed, on hold, or returned)",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields["remarks"])

    def clean(self):
        cleaned = super().clean()
        outcome = cleaned.get("outcome")
        if outcome in (
            Invoice.Status.DISPUTED,
            Invoice.Status.ON_HOLD,
            Invoice.Status.RETURNED,
        ) and not cleaned.get("remarks", "").strip():
            raise forms.ValidationError("Remarks are required for this outcome.")
        return cleaned


# ---------------------------------------------------------------------------
# Stage 8 - SIC: Issue Slip
# ---------------------------------------------------------------------------
class IssueSlipForm(forms.ModelForm):
    class Meta:
        model = IssueSlip
        fields = ["material", "department", "quantity_issued", "material_need"]
        labels = {
            "material": "Material to issue",
            "department": "Requesting department",
            "quantity_issued": "Quantity to issue",
            "material_need": "Linked material need (recommended)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["material"].queryset = Material.objects.order_by("name")
        self.fields["material_need"].queryset = MaterialNeed.objects.exclude(
            status=MaterialNeed.Status.CLOSED
        ).select_related("material", "department").order_by("-created_at")
        self.fields["material_need"].required = False
        self.fields["department"].required = False

    def clean_quantity_issued(self):
        quantity = self.cleaned_data["quantity_issued"]
        if quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than zero.")
        return quantity

    def clean(self):
        cleaned = super().clean()
        material = cleaned.get("material")
        need = cleaned.get("material_need")
        department = cleaned.get("department")
        if need:
            if material and need.material_id != material.id:
                self.add_error(
                    "material",
                    "The selected material does not match the linked need.",
                )
            if department and need.department_id != department.id:
                self.add_error(
                    "department",
                    "The department does not match the linked need.",
                )
        elif not department:
            self.add_error(
                "department",
                "Select a department when no material need is linked.",
            )
        return cleaned


class AcknowledgeIssueForm(forms.Form):
    """End user accepts or flags a condition issue."""
    CHOICES = [
        ("accept", "Acknowledge - received in good condition"),
        ("flag", "Dispute - condition issue noted"),
    ]
    decision = forms.ChoiceField(choices=CHOICES, widget=forms.RadioSelect)
    remark = forms.CharField(
        label="Condition remark (required when disputing)",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields["remark"])

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "flag" and not cleaned.get("remark", "").strip():
            raise forms.ValidationError("Please describe the condition issue.")
        return cleaned


# ---------------------------------------------------------------------------
# Stock adjustment
# ---------------------------------------------------------------------------
class StockAdjustmentForm(forms.Form):
    material = forms.ModelChoiceField(
        queryset=Material.objects.none(),
        label="Material",
    )
    delta = forms.DecimalField(
        label="Quantity change (+ receipt / - issue)",
        max_digits=12,
        decimal_places=2,
    )
    reason = forms.CharField(
        label="Reason for the adjustment",
        max_length=200,
    )
    note = forms.CharField(
        label="Additional note (optional)",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["material"].queryset = Material.objects.order_by("name")

    def clean_delta(self):
        delta = self.cleaned_data["delta"]
        if delta == 0:
            raise forms.ValidationError("The quantity change cannot be zero.")
        return delta


# Keep the old DemonstrationForm so nothing breaks in imports.
class DemonstrationForm(forms.Form):
    demonstration_value = forms.CharField(
        label="Demonstration field",
        help_text="Not connected to a database.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"
