from django import forms

from .models import (
    Delivery,
    Invoice,
    IssueSlip,
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
# Stage 1 — End User: Material Need
# ---------------------------------------------------------------------------
class MaterialNeedForm(forms.ModelForm):
    class Meta:
        model = MaterialNeed
        fields = [
            "material",
            "department",
            "area",
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
            "area": "Area / Location",
            "description": "Additional description",
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
        self.fields["area"].required = False
        self.fields["description"].required = False
        self.fields["specification"].required = False
        self.fields["needed_by"].required = False
        self.fields["purpose"].required = False


# ---------------------------------------------------------------------------
# Stage 2 — PR Creator: Purchase Request
# ---------------------------------------------------------------------------
class PurchaseRequestForm(forms.ModelForm):
    class Meta:
        model = PurchaseRequest
        fields = ["sap_pr_number", "decision_notes"]
        labels = {
            "sap_pr_number": "SAP PR number (leave blank if not yet available)",
            "decision_notes": "Notes / remarks",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["sap_pr_number"].required = False
        self.fields["decision_notes"].required = False


# ---------------------------------------------------------------------------
# Stage 3 — ODM: PR Decision
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
# Stage 4 — Specialist: Quotation
# ---------------------------------------------------------------------------
class QuotationForm(forms.ModelForm):
    class Meta:
        model = Quotation
        fields = [
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
            "score": "Weighted score (system or manual)",
            "notes": "Notes",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["lead_time_days"].required = False
        self.fields["payment_terms"].required = False
        self.fields["warranty"].required = False
        self.fields["score"].required = False
        self.fields["notes"].required = False


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
# Stage 5 — Specialist: Purchase Order
# ---------------------------------------------------------------------------
class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["sap_po_number", "total_amount"]
        labels = {
            "sap_po_number": "SAP PO number (leave blank if not yet available)",
            "total_amount": "Total order amount",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["sap_po_number"].required = False


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
# Stage 6 — SIC: Delivery / Goods Receipt
# ---------------------------------------------------------------------------
class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Delivery
        fields = [
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
            "sap_gr_number": "GR number (from SAP / plan book)",
            "remarks": "Condition / remarks",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["sap_gr_number"].required = False
        self.fields["remarks"].required = False


# ---------------------------------------------------------------------------
# Stage 7 — DCT: Invoice logging
# ---------------------------------------------------------------------------
class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ["invoice_number", "amount", "remarks"]
        labels = {
            "invoice_number": "Supplier invoice number",
            "amount": "Invoice amount",
            "remarks": "Remarks",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["remarks"].required = False


class AccountingReviewForm(forms.Form):
    """Accounting records one of four outcomes."""
    OUTCOME_CHOICES = [
        (Invoice.Status.MATCHED, "Matched — ordered, received and invoiced agree"),
        (Invoice.Status.DISPUTED, "Disputed — price or quantity differs"),
        (Invoice.Status.ON_HOLD, "On hold — invoice received but goods not yet in"),
        (Invoice.Status.RETURNED, "Returned — sent back to DCT or Procurement"),
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
# Stage 8 — SIC: Issue Slip
# ---------------------------------------------------------------------------
class IssueSlipForm(forms.ModelForm):
    class Meta:
        model = IssueSlip
        fields = ["material", "department", "quantity_issued", "material_need"]
        labels = {
            "material": "Material to issue",
            "department": "Requesting department",
            "quantity_issued": "Quantity to issue",
            "material_need": "Linked material need (optional)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_all(self)
        self.fields["material_need"].required = False
        self.fields["department"].required = False


class AcknowledgeIssueForm(forms.Form):
    """End user accepts or flags a condition issue."""
    CHOICES = [
        ("accept", "Accept — received in good condition"),
        ("flag", "Accept with remark — condition issue noted"),
    ]
    decision = forms.ChoiceField(choices=CHOICES, widget=forms.RadioSelect)
    remark = forms.CharField(
        label="Condition remark (required when flagging)",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields["remark"])

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "flag" and not cleaned.get("remark", "").strip():
            raise forms.ValidationError(
                "Please describe the condition issue."
            )
        return cleaned


# Keep the old DemonstrationForm so nothing breaks
class DemonstrationForm(forms.Form):
    demonstration_value = forms.CharField(
        label="Demonstration field",
        help_text="Not connected to a database.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "input"
