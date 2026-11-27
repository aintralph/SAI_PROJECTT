from django.conf import settings
from django.db import models

from accounts.models import Department


class Material(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    unit = models.CharField(max_length=30)
    stock_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reorder_level = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock_on_hand__gte=0),
                name="material_stock_on_hand_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(reorder_level__gte=0),
                name="material_reorder_level_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Supplier(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class MaterialNeed(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CONVERTED = "converted", "Converted to PR"
        ISSUED = "issued", "Issued"
        CLOSED = "closed", "Closed"

    reference = models.CharField(max_length=30, unique=True, db_index=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="material_needs",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        related_name="needs",
    )
    area = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    specification = models.TextField(blank=True)
    sap_material_code = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Optional SAP material code. Leave blank for a non-standard item.",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    purpose = models.TextField(blank=True)
    needed_by = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_needs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="material_need_quantity_positive",
            ),
        ]

    def __str__(self):
        return self.reference


class PurchaseRequest(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_ODM = "pending_odm", "Pending ODM Decision"
        APPROVED = "approved", "Approved"
        RETURNED = "returned", "Returned for Correction"
        REJECTED = "rejected", "Rejected"

    reference = models.CharField(max_length=30, unique=True, db_index=True)
    material_need = models.ForeignKey(
        MaterialNeed,
        on_delete=models.PROTECT,
        related_name="purchase_requests",
    )
    sap_pr_number = models.CharField(max_length=50, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    decision_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_prs",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_prs",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["material_need"],
                name="one_purchase_request_per_need",
            ),
        ]

    def __str__(self):
        return self.reference


class Quotation(models.Model):
    reference = models.CharField(max_length=30, unique=True, db_index=True)
    purchase_request = models.ForeignKey(
        PurchaseRequest,
        on_delete=models.PROTECT,
        related_name="quotations",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="quotations",
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    payment_terms = models.CharField(max_length=150, blank=True)
    warranty = models.CharField(max_length=150, blank=True)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_selected = models.BooleanField(default=False)
    selection_notes = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_quotations",
    )
    selected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="selected_quotations",
    )
    selected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="quotation_unit_price_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="quotation_total_amount_non_negative",
            ),
            models.UniqueConstraint(
                fields=["purchase_request"],
                condition=models.Q(is_selected=True),
                name="one_selected_quotation_per_request",
            ),
        ]

    def __str__(self):
        return self.reference


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SITE_REVIEW = "site_review", "Pending Site Lead Review"
        STRATEGIC_APPROVAL = "strategic_approval", "Pending Strategic Approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        PARTIALLY_DELIVERED = "partially_delivered", "Partially Delivered"
        DELIVERED = "delivered", "Delivered"

    reference = models.CharField(max_length=30, unique=True, db_index=True)
    purchase_request = models.ForeignKey(
        PurchaseRequest,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    quotation = models.OneToOneField(
        Quotation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="purchase_order",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    sap_po_number = models.CharField(max_length=50, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_pos",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_pos",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_pos",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default="")
    approval_notes = models.TextField(blank=True, default="")
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="purchase_order_total_amount_non_negative",
            ),
            models.UniqueConstraint(
                fields=["purchase_request"],
                name="one_purchase_order_per_request",
            ),
        ]

    def __str__(self):
        return self.reference


class Delivery(models.Model):
    reference = models.CharField(max_length=30, unique=True, db_index=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    quantity_received = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_date = models.DateField()
    sap_gr_number = models.CharField(max_length=50, blank=True)
    remarks = models.TextField(blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_deliveries",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Deliveries"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_received__gt=0),
                name="delivery_quantity_positive",
            ),
        ]

    def __str__(self):
        return self.reference


class IssueSlip(models.Model):
    class Status(models.TextChoices):
        ISSUED = "issued", "Issued (Awaiting Acknowledgement)"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        DISPUTED = "disputed", "Disputed by Requester"

    reference = models.CharField(max_length=30, unique=True, db_index=True)
    material_need = models.ForeignKey(
        MaterialNeed,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="issue_slips",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        related_name="issue_slips",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="issue_slips",
    )
    quantity_issued = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ISSUED,
        db_index=True,
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_slips",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="acknowledged_slips",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    condition_notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-issued_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_issued__gt=0),
                name="issue_slip_quantity_positive",
            ),
        ]

    def __str__(self):
        return self.reference


class Invoice(models.Model):
    class Status(models.TextChoices):
        LOGGED = "logged", "Logged by DCT"
        HANDED_OFF = "handed_off", "Handed Off to Accounting"
        MATCHED = "matched", "Matched and Cleared"
        DISPUTED = "disputed", "Disputed"
        ON_HOLD = "on_hold", "On Hold (No Goods)"
        RETURNED = "returned", "Returned"

    reference = models.CharField(max_length=30, unique=True, db_index=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    delivery = models.ForeignKey(
        Delivery,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
    )
    invoice_number = models.CharField(max_length=60)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.LOGGED,
        db_index=True,
    )
    remarks = models.TextField(blank=True)
    review_remarks = models.TextField(blank=True, default="")
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="logged_invoices",
    )
    handed_off_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="handed_off_invoices",
    )
    handed_off_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_invoices",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name="invoice_amount_non_negative",
            ),
        ]

    def __str__(self):
        return self.reference


class StockMovement(models.Model):
    class Reason(models.TextChoices):
        DELIVERY_RECEIPT = "delivery_receipt", "Delivery receipt"
        ISSUE = "issue", "Issue to requester"
        ADJUSTMENT = "adjustment", "Stock adjustment"

    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    delta = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(
        max_length=30,
        choices=Reason.choices,
        default=Reason.ADJUSTMENT,
        db_index=True,
    )
    note = models.TextField(blank=True, default="")
    delivery = models.ForeignKey(
        Delivery,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    issue = models.ForeignKey(
        IssueSlip,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(delta=0),
                name="stock_movement_delta_non_zero",
            ),
        ]

    def __str__(self):
        return f"{self.material} {self.delta:+} ({self.get_reason_display()})"


class ReferenceCounter(models.Model):
    prefix = models.CharField(max_length=10)
    year = models.PositiveIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["prefix", "year"],
                name="unique_reference_counter_per_prefix_year",
            ),
            models.CheckConstraint(
                condition=models.Q(last_value__gte=0),
                name="reference_counter_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.prefix}-{self.year}: {self.last_value}"


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    module = models.CharField(max_length=30, db_index=True)
    record_reference = models.CharField(max_length=30, db_index=True)
    action = models.CharField(max_length=100)
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30, blank=True)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.module} {self.record_reference}: {self.action}"
