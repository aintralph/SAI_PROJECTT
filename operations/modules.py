from django.urls import reverse

from accounts.roles import ROLE_ACCESS, ROLES

def _module(key, label):
    return {
        "key": key,
        "label": label,
        "description": "Open the records for this module.",
        "url_name": "records",
        "access": {
            role_slug: access[key]
            for role_slug, access in ROLE_ACCESS.items()
            if key in access
        },
    }


MODULES = [
    _module("needs", "Material needs"),
    _module("requests", "My requests"),
    _module("quotations", "Quotations"),
    _module("orders", "Purchase orders"),
    _module("deliveries", "Deliveries"),
    _module("issues", "Issue slips"),
    _module("invoices", "Invoices"),
]


ROLE_LABELS = {role["slug"]: role["label"] for role in ROLES}


def role_slugs_for_user(user):
    if not getattr(user, "is_authenticated", False):
        return ()
    return tuple(
        role_slug
        for role_slug in user.groups.values_list("name", flat=True)
        if role_slug in ROLE_ACCESS
    )


def _entry(module, access):
    return {
        "key": module["key"],
        "label": module["label"],
        "description": module["description"],
        "url_name": module["url_name"],
        "url": reverse(module["url_name"], args=[module["key"]]),
        "access": access,
    }


def modules_for_role(role_slug):
    access_by_key = ROLE_ACCESS.get(role_slug, {})
    return [
        _entry(module, access_by_key[module["key"]])
        for module in MODULES
        if module["key"] in access_by_key
    ]


def modules_for_user(user):
    access_by_key = {}
    for role_slug in role_slugs_for_user(user):
        for key, access in ROLE_ACCESS[role_slug].items():
            if access == "act" or key not in access_by_key:
                access_by_key[key] = access
    return [
        _entry(module, access_by_key[module["key"]])
        for module in MODULES
        if module["key"] in access_by_key
    ]
