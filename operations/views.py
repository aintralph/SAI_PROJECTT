from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from accounts.views import render_access_denied

from .forms import DemonstrationForm
from .modules import (
    MODULES,
    ROLE_LABELS,
    modules_for_user,
    role_slugs_for_user,
)


def _role_context(user):
    role_slugs = role_slugs_for_user(user)
    if not role_slugs:
        return None
    return {
        "label": ", ".join(ROLE_LABELS[slug] for slug in role_slugs),
    }


@login_required
def dashboard(request):
    modules = modules_for_user(request.user)
    role_slugs = role_slugs_for_user(request.user)
    records_connected = False
    role = None
    description = None
    if role_slugs:
        role = {
            "label": ", ".join(ROLE_LABELS[slug] for slug in role_slugs),
        }
        if role_slugs == ("enduser-maintenance-lead",):
            description = (
                "Record indirect material needs for your department and "
                "acknowledge issued items."
            )

    action_module = next(
        (module for module in modules if module["access"] == "act"),
        None,
    )
    primary_action = (
        {
            "label": "Open " + action_module["label"],
            "url": action_module["url"],
        }
        if action_module
        else {"label": "Dashboard", "url": request.path}
    )

    metrics = [
        {
            "label": "Open needs",
            "value": None,
            "unit": "records",
            "source": "Not connected",
        },
        {
            "label": "Awaiting my action",
            "value": None,
            "unit": "records",
            "source": "Not connected",
        },
        {
            "label": "Delivered",
            "value": None,
            "unit": "records",
            "source": "Not connected",
        },
        {
            "label": "Stock alerts",
            "value": None,
            "unit": "items",
            "source": "Not connected",
        },
    ]
    return render(
        request,
        "operations/dashboard.html",
        {
            "role": role,
            "role_description": description,
            "records_connected": records_connected,
            "metrics": metrics,
            "modules": modules,
            "module_count": len(modules),
            "queue": [],
            "status": {"source": "Manual entry", "last_sync": "None"},
            "crumb_parent": "Workspace",
            "crumb_current": "Dashboard",
            "nav_modules": modules,
            "active_module": None,
            "primary_action": primary_action,
        },
    )


@login_required
def records(request, module):
    module_definition = next(
        (entry for entry in MODULES if entry["key"] == module),
        None,
    )
    if module_definition is None:
        raise Http404("Unknown module.")

    modules = modules_for_user(request.user)
    permitted_module = next(
        (entry for entry in modules if entry["key"] == module),
        None,
    )
    if permitted_module is None:
        return render_access_denied(request)

    rows = []
    # Set this to True only when this view returns rows from a queryset.
    records_connected = False
    return render(
        request,
        "operations/records.html",
        {
            "module": permitted_module,
            "columns": [],
            "rows": rows,
            "record_count": len(rows),
            "records_connected": records_connected,
            "data_source": "Not connected",
            "title": "No records",
            "body": "There are no records in this module.",
            "role": _role_context(request.user),
            "crumb_parent": "Workspace",
            "crumb_current": permitted_module["label"],
            "nav_modules": modules,
            "active_module": module,
        },
    )


@login_required
def need_detail(request, module, reference):
    module_definition = next(
        (entry for entry in MODULES if entry["key"] == module),
        None,
    )
    if module_definition is None:
        raise Http404("Unknown module.")

    modules = modules_for_user(request.user)
    permitted_module = next(
        (entry for entry in modules if entry["key"] == module),
        None,
    )
    if permitted_module is None:
        return render_access_denied(request)

    action_message = (
        "This role has read-only access, so no record changes are available."
        if permitted_module["access"] == "read"
        else "This record cannot be acted on until records are connected to a database."
    )
    return render(
        request,
        "operations/need_detail.html",
        {
            "module": permitted_module,
            "reference": reference,
            "status": "Not connected",
            "fields": [],
            "chain": [],
            "actions": [],
            "action_message": action_message,
            "role": _role_context(request.user),
            "crumb_parent": permitted_module["label"],
            "crumb_current": reference,
            "nav_modules": modules,
            "active_module": module,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def form_page(request, module):
    module_definition = next(
        (entry for entry in MODULES if entry["key"] == module),
        None,
    )
    if module_definition is None:
        raise Http404("Unknown module.")

    modules = modules_for_user(request.user)
    permitted_module = next(
        (entry for entry in modules if entry["key"] == module),
        None,
    )
    if permitted_module is None or permitted_module["access"] != "act":
        return render_access_denied(request)

    form = DemonstrationForm(
        request.POST if request.method == "POST" else None
    )
    if request.method == "POST":
        form.is_valid()

    return render(
        request,
        "operations/form_page.html",
        {
            "module": permitted_module,
            "form": form,
            "cancel_url": permitted_module["url"],
            "role": _role_context(request.user),
            "crumb_parent": permitted_module["label"],
            "crumb_current": "Demonstration form",
            "nav_modules": modules,
            "active_module": module,
        },
    )
