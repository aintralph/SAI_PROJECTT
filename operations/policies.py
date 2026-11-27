"""Central server-side access policy for the operational workspace.

Views and services must use these helpers instead of assuming that a visible
link implies authorization. Module access is deny-by-default: a role only has
the access declared in ``accounts.roles.ROLE_ACCESS``.
"""

from accounts.roles import capabilities_for
from django.db.models import Q

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
from .modules import modules_for_user, role_slugs_for_user


MODULE_MODELS = {
    "needs": MaterialNeed,
    "requests": PurchaseRequest,
    "quotations": Quotation,
    "orders": PurchaseOrder,
    "deliveries": Delivery,
    "stock": Material,
    "issues": IssueSlip,
    "invoices": Invoice,
}

# Roles that may read the module beyond the current user's own records.
_BROAD_READ_ROLES = {
    "needs": {
        "pr-creator",
        "odm",
        "procurement-specialist",
    },
    "requests": {
        "pr-creator",
        "odm",
        "procurement-specialist",
        "procurement-site-lead",
        "procurement-strategic-lead",
        "sic-stockroom-gr-creator",
    },
    "deliveries": {
        "sic-stockroom-gr-creator",
        "dct",
    },
    "issues": {
        "sic-stockroom-gr-creator",
    },
}

_CREATE_CAPABILITIES = {
    "needs": ("create_need",),
    "requests": ("prepare_pr", "record_pr_reference"),
    "quotations": ("manage_quotations",),
    "orders": ("record_po_reference",),
    "deliveries": ("record_delivery", "record_gr"),
    "stock": ("manage_stock",),
    "issues": ("record_issue",),
    "invoices": ("log_invoice",),
}


def user_roles(user):
    if not getattr(user, "is_authenticated", False):
        return ()
    return role_slugs_for_user(user)


def user_capabilities(user):
    capabilities = set()
    for slug in user_roles(user):
        capabilities.update(capabilities_for(slug))
    return frozenset(capabilities)


def has_capability(user, capability):
    return capability in user_capabilities(user)


def has_all_capabilities(user, *capabilities):
    granted = user_capabilities(user)
    return all(capability in granted for capability in capabilities)


def module_entry_for_user(user, module_key):
    return next((entry for entry in modules_for_user(user) if entry["key"] == module_key), None)


def module_access_for_user(user, module_key):
    entry = module_entry_for_user(user, module_key)
    return entry["access"] if entry else None


def can_create_module(user, module_key):
    capabilities = _CREATE_CAPABILITIES.get(module_key)
    if not capabilities or module_entry_for_user(user, module_key) is None:
        return False
    return has_all_capabilities(user, *capabilities)


def _enduser_only(user, module_key):
    roles = set(user_roles(user))
    if "enduser-maintenance-lead" not in roles:
        return False
    return not (roles & _BROAD_READ_ROLES.get(module_key, set()))


def scope_queryset(user, module_key, queryset):
    """Return only the rows the authenticated user may see for a module."""

    if module_entry_for_user(user, module_key) is None:
        return queryset.none()

    roles = set(user_roles(user))

    if module_key == "needs":
        if roles & {"odm", "procurement-specialist"}:
            return queryset
        access_filter = Q(pk__in=[])
        if "enduser-maintenance-lead" in roles:
            access_filter |= Q(created_by=user)
        if "pr-creator" in roles:
            access_filter |= Q(status=MaterialNeed.Status.OPEN)
        return queryset.filter(access_filter)

    if not _enduser_only(user, module_key):
        return queryset

    if module_key == "requests":
        return queryset.filter(material_need__created_by=user)
    if module_key == "deliveries":
        return queryset.filter(
            purchase_order__purchase_request__material_need__created_by=user
        )
    if module_key == "issues":
        return queryset.filter(material_need__created_by=user)
    return queryset


def scoped_model_queryset(user, module_key):
    model = MODULE_MODELS[module_key]
    return scope_queryset(user, module_key, model.objects.all())


def can_view_object(user, module_key, obj):
    if obj is None:
        return False
    model = MODULE_MODELS[module_key]
    return scope_queryset(
        user, module_key, model.objects.filter(pk=obj.pk)
    ).exists()


def can_acknowledge_issue(user, issue):
    """Only the creator of the linked need may acknowledge or dispute it."""

    if not has_capability(user, "acknowledge_issue"):
        return False
    need = issue.material_need
    return bool(need and need.created_by_id == user.id)


def can_select_quotation(user, quotation):
    if not has_capability(user, "manage_quotations"):
        return False
    return quotation.purchase_request.status == PurchaseRequest.Status.APPROVED
