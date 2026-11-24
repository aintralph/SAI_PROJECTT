CAPABILITIES = (
    "manage_users",
    "view_audit",
    "view_needs_own",
    "create_need",
    "acknowledge_issue",
    "prepare_pr",
    "record_pr_reference",
    "record_pr_decision",
    "manage_quotations",
    "record_po_reference",
    "review_po",
    "approve_po",
    "record_delivery",
    "record_gr",
    "manage_stock",
    "record_issue",
    "log_invoice",
    "record_handoff",
    "review_invoice",
)

ROLES = [
    {
        "slug": "system-administrator",
        "label": "System Administrator",
        "purpose": (
            "Provisions users and roles, and reads the audit trail. "
            "No operational access to procurement records."
        ),
        "capabilities": ("manage_users", "view_audit"),
    },
    {
        "slug": "enduser-maintenance-lead",
        "label": "End-user / Maintenance Lead",
        "purpose": (
            "Records indirect material needs for the department and "
            "acknowledges issued items."
        ),
        "capabilities": (
            "view_needs_own",
            "create_need",
            "acknowledge_issue",
        ),
    },
    {
        "slug": "pr-creator",
        "label": "PR Creator",
        "purpose": "Prepares and encodes purchase requests from approved needs.",
        "capabilities": (
            "view_needs_own",
            "prepare_pr",
            "record_pr_reference",
        ),
    },
    {
        "slug": "odm",
        "label": "ODM",
        "purpose": "Reviews a purchase request and records the decision.",
        "capabilities": ("view_needs_own", "record_pr_decision"),
    },
    {
        "slug": "procurement-specialist",
        "label": "Procurement Specialist",
        "purpose": "Manages quotations and starts the purchase order.",
        "capabilities": ("manage_quotations", "record_po_reference"),
    },
    {
        "slug": "procurement-site-lead",
        "label": "Procurement Site Lead",
        "purpose": "Performs the first review of a purchase order.",
        "capabilities": ("review_po",),
    },
    {
        "slug": "procurement-strategic-lead",
        "label": "Procurement Strategic Lead",
        "purpose": "Gives final approval of a purchase order.",
        "capabilities": ("approve_po",),
    },
    {
        "slug": "sic-stockroom-gr-creator",
        "label": "SIC / Stockroom / GR Creator",
        "purpose": (
            "Receives goods, records the goods receipt reference, manages stock "
            "and records issues."
        ),
        "capabilities": (
            "record_delivery",
            "record_gr",
            "manage_stock",
            "record_issue",
        ),
    },
    {
        "slug": "dct",
        "label": "DCT",
        "purpose": "Logs invoice documents and records the handoff to Accounting.",
        "capabilities": ("log_invoice", "record_handoff"),
    },
    {
        "slug": "accounting-finance",
        "label": "Accounting & Finance",
        "purpose": "Reviews invoice documents and records the outcome.",
        "capabilities": ("review_invoice",),
    },
]

ROLE_ACCESS = {
    "system-administrator": {},
    "enduser-maintenance-lead": {
        "needs": "act",
        "requests": "read",
        "deliveries": "read",
        "issues": "act",
    },
    "pr-creator": {
        "needs": "read",
        "requests": "act",
    },
    "odm": {
        "needs": "read",
        "requests": "act",
    },
    "procurement-specialist": {
        "needs": "read",
        "requests": "read",
        "quotations": "act",
        "orders": "act",
    },
    "procurement-site-lead": {
        "requests": "read",
        "quotations": "read",
        "orders": "act",
    },
    "procurement-strategic-lead": {
        "requests": "read",
        "quotations": "read",
        "orders": "act",
    },
    "sic-stockroom-gr-creator": {
        "requests": "read",
        "orders": "read",
        "deliveries": "act",
        "issues": "act",
    },
    "dct": {
        "orders": "read",
        "deliveries": "read",
        "invoices": "act",
    },
    "accounting-finance": {
        "orders": "read",
        "invoices": "act",
    },
}


def role_by_slug(slug):
    return next((role for role in ROLES if role["slug"] == slug), None)


def all_slugs():
    return [role["slug"] for role in ROLES]


def capabilities_for(slug):
    role = role_by_slug(slug)
    return tuple(role["capabilities"]) if role is not None else ()


def validate_roles():
    slugs = all_slugs()
    if len(slugs) != len(set(slugs)):
        raise ValueError("Role slugs must be unique.")

    if len(CAPABILITIES) != len(set(CAPABILITIES)):
        raise ValueError("CAPABILITIES must not contain duplicates.")

    known_capabilities = set(CAPABILITIES)
    for role in ROLES:
        if not role["capabilities"]:
            raise ValueError("Role %r must have at least one capability." % role["slug"])
        unknown = set(role["capabilities"]) - known_capabilities
        if unknown:
            raise ValueError(
                "Role %r uses unknown capabilities: %s"
                % (role["slug"], ", ".join(sorted(unknown)))
            )

    unknown_roles = set(ROLE_ACCESS) - set(slugs)
    if unknown_roles:
        raise ValueError(
            "ROLE_ACCESS contains unknown role slugs: %s"
            % ", ".join(sorted(unknown_roles))
        )


validate_roles()
