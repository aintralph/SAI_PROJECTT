from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.shortcuts import render, resolve_url
from django.urls import reverse_lazy

from .forms import StyledAuthenticationForm, StyledPasswordChangeForm
from .roles import role_by_slug

ROLE_PURPOSES = {
    "enduser-maintenance-lead": (
        "Record indirect material needs for your department and "
        "acknowledge issued items."
    ),
}


def _role_label(role_slugs):
    from operations.modules import ROLE_LABELS

    return ", ".join(ROLE_LABELS[slug] for slug in role_slugs) if role_slugs else None


def _shell_context(request, crumb_current):
    from operations.modules import modules_for_user, role_slugs_for_user

    role_slugs = role_slugs_for_user(request.user)
    modules = modules_for_user(request.user)
    return {
        "role": {"label": _role_label(role_slugs)} if role_slugs else None,
        "nav_modules": modules,
        "active_module": None,
        "crumb_parent": "Account",
        "crumb_current": crumb_current,
    }


def _post_login_redirect(user):
    """Return the correct URL for a user after a successful login."""
    from operations.modules import modules_for_user, role_slugs_for_user

    # Superuser or staff with no SIA role → Django Admin
    if user.is_superuser:
        return resolve_url("admin:index")

    role_slugs = role_slugs_for_user(user)

    # system-administrator has no operational modules → access map
    if "system-administrator" in role_slugs:
        return resolve_url("access_map")

    # Any role that has operational modules → Workspace Dashboard
    if modules_for_user(user):
        return resolve_url("dashboard")

    # Logged in but no recognized role assigned yet → My workspaces page
    return resolve_url("overview")


def root_redirect(request):
    """
    Entry point for the site root ('/').

    - Anonymous users  → login page
    - Authenticated users → role-based destination (same logic as post-login)
    """
    from django.shortcuts import redirect as _redirect

    if not request.user.is_authenticated:
        return _redirect("login")
    return _redirect(_post_login_redirect(request.user))


class ProjectLoginView(LoginView):
    authentication_form = StyledAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return _post_login_redirect(self.request.user)


class ProjectPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    form_class = StyledPasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("dashboard")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_shell_context(self.request, "Change password"))
        return context


@login_required
def access_map(request):
    from operations.modules import (
        MODULES,
        ROLE_ACCESS,
        ROLE_LABELS,
        modules_for_role,
        role_slugs_for_user,
    )

    role_slugs = role_slugs_for_user(request.user)
    role_maps = []
    for role_slug in role_slugs:
        allowed = modules_for_role(role_slug)
        allowed_keys = {module["key"] for module in allowed}
        permissions = ROLE_ACCESS[role_slug]
        capabilities = []
        for module in allowed:
            if permissions[module["key"]] == "act":
                capabilities.append(
                    "Create and change records in %s." % module["label"]
                )
            else:
                capabilities.append(
                    "List and open records in %s; no write control." % module["label"]
                )
        role_maps.append(
            {
                "label": ROLE_LABELS[role_slug],
                "purpose": ROLE_PURPOSES.get(
                    role_slug,
                    "Purpose has not been supplied.",
                ),
                "allowed_modules": allowed,
                "unavailable_modules": [
                    module for module in MODULES if module["key"] not in allowed_keys
                ],
                "capabilities": capabilities,
            }
        )

    context = _shell_context(request, "Access map")
    context["roles"] = role_maps
    return render(request, "accounts/access_map.html", context)


@login_required
def overview(request):
    from operations.modules import ROLE_LABELS, role_slugs_for_user

    roles = [
        {
            "slug": role_slug,
            "label": ROLE_LABELS[role_slug],
        }
        for role_slug in role_slugs_for_user(request.user)
    ]
    context = _shell_context(request, "My workspaces")
    context["roles"] = roles
    return render(request, "accounts/overview.html", context)


def render_access_denied(request):
    context = _shell_context(request, "Access denied")
    context["attempted_route"] = request.get_full_path()
    context["denial_reason"] = "You do not have permission to open this page."
    return render(
        request,
        "accounts/access_denied.html",
        context,
        status=403,
    )


@login_required
def access_denied(request):
    return render_access_denied(request)
