from django.contrib import admin

from .models import (
    AuditLog,
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

admin.site.register(Material)
admin.site.register(Supplier)
admin.site.register(MaterialNeed)
admin.site.register(PurchaseRequest)
admin.site.register(Quotation)
admin.site.register(PurchaseOrder)
admin.site.register(Delivery)
admin.site.register(IssueSlip)
admin.site.register(Invoice)
admin.site.register(AuditLog)
