from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.utils import timezone

from operations.models import AuditLog

from .forms import (
    StyledAuthenticationForm,
    StyledPasswordChangeForm,
    SystemAdminAccountCreateForm,
    SystemAdminAccountEditForm,
)
from .models import UserProfile
from .roles import ROLES, all_slugs


def _role_label(role_slugs):
    from operations.modules import ROLE_LABELS
    return ", ".join(ROLE_LABELS[slug] for slug in role_slugs) if role_slugs else None


def _shell_context(request, crumb_current):
    from operations.modules import modules_for_user, role_slugs_for_user

    role_slugs = role_slugs_for_user(request.user)
    modules = modules_for_user(request.user)
    is_sysadmin = "system-administrator" in role_slugs
    role_label = "System Administrator" if is_sysadmin else _role_label(role_slugs)
    if request.user.is_superuser:
        role_label = "Django Superuser"
    return {
        "role": {"label": role_label} if role_label else None,
        "nav_modules": [] if is_sysadmin or request.user.is_superuser else modules,
        "active_module": None,
        "crumb_parent": "Account",
        "crumb_current": crumb_current,
        "is_system_administrator": is_sysadmin,
        "is_django_superuser": request.user.is_superuser,
    }


def _post_login_redirect(user):
    from operations.modules import modules_for_user, role_slugs_for_user

    if user.is_superuser:
        return resolve_url("admin:index")
    role_slugs = role_slugs_for_user(user)
    if "system-administrator" in role_slugs:
        return resolve_url("system_admin_dashboard")
    if modules_for_user(user):
        return resolve_url("dashboard")
    return resolve_url("access_denied")


def root_redirect(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return redirect(_post_login_redirect(request.user))


class ProjectLoginView(LoginView):
    authentication_form = StyledAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return _post_login_redirect(self.request.user)


class ProjectPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    form_class = StyledPasswordChangeForm
    template_name = "accounts/password_change.html"

    def get_success_url(self):
        return _post_login_redirect(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_shell_context(self.request, "Change password"))
        return context


def render_access_denied(request):
    context = _shell_context(request, "Access denied")
    context["attempted_route"] = request.get_full_path()
    context["denial_reason"] = "You do not have permission to open this page."
    return render(request, "accounts/access_denied.html", context, status=403)


@login_required
def access_denied(request):
    return render_access_denied(request)


@login_required
def profile(request):
    role = _recognized_role(request.user)
    profile = getattr(request.user, "profile", None)
    context = _shell_context(request, "Profile")
    context.update({
        "profile": profile,
        "recognized_role": role,
    })
    context["crumb_parent"] = "Account"
    return render(request, "accounts/profile.html", context)


def system_administrator_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser and not request.user.groups.filter(name="system-administrator").exists():
            return render_access_denied(request)
        return view_func(request, *args, **kwargs)
    return wrapped


def _recognized_role(user):
    names = set(user.groups.values_list("name", flat=True))
    for role in ROLES:
        if role["slug"] in names:
            return role
    return None


def _replace_recognized_role(user, role_slug):
    recognized = set(all_slugs())
    existing = list(user.groups.filter(name__in=recognized))
    old_slugs = [group.name for group in existing]
    if existing:
        user.groups.remove(*existing)
    if role_slug:
        group, _ = Group.objects.get_or_create(name=role_slug)
        user.groups.add(group)
    return old_slugs


def _audit_account(actor, account, action, old_status="", new_status="", details=""):
    AuditLog.objects.create(
        actor=actor,
        module="accounts",
        record_reference=account.username[:30],
        action=action,
        old_status=old_status,
        new_status=new_status,
        details=details[:500],
    )


@system_administrator_required
def system_admin_dashboard(request):
    User = get_user_model()
    users = User.objects.all()
    known_slugs = set(all_slugs())
    active_accounts = users.filter(is_active=True).count()
    staff_accounts = users.filter(is_active=True, is_staff=True).count()

    now = timezone.now()
    week_start = (now - timezone.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    failed_signins = AuditLog.objects.filter(module="auth", action="Login failed", created_at__gte=week_start).count()

    active_no_role = sum(
        1
        for user in users.filter(is_active=True).prefetch_related("groups")
        if not (set(user.groups.values_list("name", flat=True)) & known_slugs)
    )
    role_waiting = []
    for role in ROLES:
        if not users.filter(is_active=True, groups__name=role["slug"]).exists():
            role_waiting.append(role["label"])

    recent_users = users.select_related("profile").prefetch_related("groups").order_by("-last_login", "-date_joined")[:8]
    context = _shell_context(request, "Dashboard")
    context.update({
        "metrics": [
            {"label": "Active accounts", "value": active_accounts, "unit": "users", "source": "Enabled accounts"},
            {"label": "Staff accounts", "value": staff_accounts, "unit": "active", "source": "Django staff"},
            {"label": "Role groups", "value": len(known_slugs), "unit": "known", "source": "Code-defined SIA roles"},
            {"label": "Failed sign-ins", "value": failed_signins, "unit": "this week", "source": "Sanitized audit entries"},
        ],
        "recent_users": recent_users,
        "active_no_role": active_no_role,
        "role_waiting": role_waiting,
    })
    context["crumb_parent"] = "Administration"
    return render(request, "accounts/system_admin/dashboard.html", context)


@system_administrator_required
def system_admin_accounts(request):
    User = get_user_model()
    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")
    role_filter = request.GET.get("role", "")
    users = User.objects.all().select_related("profile").prefetch_related("groups")
    search_suggestions = []
    seen_account_ids = set()
    for account in users.order_by("username").distinct()[:30]:
        if account.pk in seen_account_ids:
            continue
        seen_account_ids.add(account.pk)
        full_name = account.get_full_name()
        secondary = " - ".join(value for value in (full_name, account.email) if value)
        search_suggestions.append({
            "value": account.username,
            "primary": account.username,
            "secondary": secondary,
            "filter": " ".join(value for value in (
                account.username,
                account.first_name,
                account.last_name,
                full_name,
                account.email,
            ) if value),
        })
        if len(search_suggestions) >= 30:
            break
    known_slugs = set(all_slugs())
    summary = {
        "total": users.count(),
        "active": users.filter(is_active=True).count(),
        "staff": users.filter(is_staff=True).count(),
        "no_role": users.exclude(groups__name__in=known_slugs).distinct().count(),
    }
    if search:
        users = users.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
        )
    if status_filter == "active":
        users = users.filter(is_active=True)
    elif status_filter == "inactive":
        users = users.filter(is_active=False)
    if role_filter == "none":
        users = users.exclude(groups__name__in=all_slugs())
    elif role_filter in all_slugs():
        users = users.filter(groups__name=role_filter)

    users = users.order_by("username").distinct()
    page = Paginator(users, 25).get_page(request.GET.get("page"))
    for account in page.object_list:
        name_parts = [account.first_name, account.last_name]
        account.initials = "".join(part[:1].upper() for part in name_parts if part) or account.username[:2].upper()
        recognized_role = _recognized_role(account)
        account.recognized_role_label = recognized_role["label"] if recognized_role else None
    context = _shell_context(request, "Accounts")
    context.update({
        "page_obj": page,
        "search": search,
        "status_filter": status_filter,
        "role_filter": role_filter,
        "roles": ROLES,
        "summary": summary,
        "search_suggestions": search_suggestions,
    })
    context["crumb_parent"] = "Administration"
    return render(request, "accounts/system_admin/account_list.html", context)


@system_administrator_required
@transaction.atomic
def system_admin_account_create(request):
    if request.method == "POST":
        form = SystemAdminAccountCreateForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = form.cleaned_data["is_active"]
            user.is_staff = False
            user.is_superuser = False
            user.save()
            role_slug = form.cleaned_data["role"]
            _replace_recognized_role(user, role_slug)
            department = form.cleaned_data["department"]
            employee_id = form.cleaned_data["employee_id"].strip()
            if department or employee_id:
                UserProfile.objects.update_or_create(
                    user=user,
                    defaults={"department": department, "employee_id": employee_id or None},
                )
            _audit_account(
                request.user,
                user,
                "Account created",
                new_status="active" if user.is_active else "inactive",
                details="Role: %s" % (role_slug or "none"),
            )
            messages.success(request, "Account created.")
            return redirect("system_admin_accounts")
    else:
        form = SystemAdminAccountCreateForm(initial={"is_active": True})
    context = _shell_context(request, "Create account")
    context.update({"form": form})
    context["crumb_parent"] = "Administration"
    return render(request, "accounts/system_admin/account_form.html", context)


@system_administrator_required
@transaction.atomic
def system_admin_account_edit(request, user_id):
    User = get_user_model()
    account = get_object_or_404(User.objects.prefetch_related("groups"), pk=user_id)
    if not request.user.is_superuser and (account.is_staff or account.is_superuser):
        return render_access_denied(request)
    old_role = _recognized_role(account)
    old_active = account.is_active

    if request.method == "POST":
        form = SystemAdminAccountEditForm(request.POST, instance=account)
        if form.is_valid():
            if account.pk == request.user.pk and form.cleaned_data["is_active"] is False:
                form.add_error("is_active", "You cannot deactivate your currently signed-in account.")
            else:
                account = form.save(commit=False)
                account.save()
                role_slug = form.cleaned_data["role"]
                _replace_recognized_role(account, role_slug)

                department = form.cleaned_data["department"]
                employee_id = form.cleaned_data["employee_id"].strip()
                if department or employee_id:
                    UserProfile.objects.update_or_create(
                        user=account,
                        defaults={"department": department, "employee_id": employee_id or None},
                    )
                elif hasattr(account, "profile"):
                    account.profile.department = None
                    account.profile.employee_id = None
                    account.profile.save(update_fields=["department", "employee_id"])

                if (old_role and old_role["slug"] != role_slug) or (not old_role and role_slug):
                    _audit_account(
                        request.user,
                        account,
                        "Role changed",
                        old_status=old_role["label"] if old_role else "No SIA role",
                        new_status=role_slug or "No SIA role",
                        details="Recognized SIA role changed.",
                    )
                if old_active != account.is_active:
                    _audit_account(
                        request.user,
                        account,
                        "Account activation changed",
                        old_status="active" if old_active else "inactive",
                        new_status="active" if account.is_active else "inactive",
                    )
                _audit_account(
                    request.user,
                    account,
                    "Account profile changed",
                    details="Profile, account status, or profile fields updated.",
                )
                messages.success(request, "Account updated.")
                return redirect("system_admin_accounts")
    else:
        form = SystemAdminAccountEditForm(instance=account)
    context = _shell_context(request, "Edit account")
    context.update({"form": form, "account": account})
    context["crumb_parent"] = "Administration"
    return render(request, "accounts/system_admin/account_form.html", context)


@system_administrator_required
def system_admin_role_groups(request):
    User = get_user_model()
    role_rows = []
    for role in ROLES:
        members = User.objects.filter(groups__name=role["slug"])
        role_rows.append({
            **role,
            "active_member_count": members.filter(is_active=True).distinct().count(),
            "total_member_count": members.distinct().count(),
        })
    context = _shell_context(request, "Role groups")
    context.update({"role_rows": role_rows})
    context["crumb_parent"] = "Administration"
    return render(request, "accounts/system_admin/role_groups.html", context)


@system_administrator_required
def system_admin_audit_log(request):
    authorized_entries = AuditLog.objects.select_related("actor").all()
    entries = authorized_entries
    search = request.GET.get("q", "").strip()
    module_filter = request.GET.get("module", "")
    action_filter = request.GET.get("action", "")
    if search:
        entries = entries.filter(
            Q(record_reference__icontains=search)
            | Q(details__icontains=search)
            | Q(actor__username__icontains=search)
        )
    if module_filter:
        entries = entries.filter(module=module_filter)
    if action_filter:
        entries = entries.filter(action__icontains=action_filter)
    page = Paginator(entries.order_by("-created_at"), 25).get_page(request.GET.get("page"))
    modules = AuditLog.objects.values_list("module", flat=True).distinct().order_by("module")
    audit_suggestions = []
    seen_values = set()
    for entry in authorized_entries.order_by("-created_at").select_related("actor")[:100]:
        values = (
            ("record_reference", entry.record_reference),
            ("actor", entry.actor.username if entry.actor_id else ""),
        )
        for kind, value in values:
            value = (value or "").strip()
            if not value or value in seen_values:
                continue
            seen_values.add(value)
            audit_suggestions.append({
                "value": value,
                "primary": value,
                "secondary": {
                    "record_reference": "Record/reference",
                    "actor": "Actor",
                }[kind],
                "filter": value,
            })
            if len(audit_suggestions) >= 30:
                break
        if len(audit_suggestions) >= 30:
            break
    context = _shell_context(request, "Audit log")
    context.update({
        "page_obj": page,
        "search": search,
        "module_filter": module_filter,
        "action_filter": action_filter,
        "modules": modules,
        "audit_suggestions": audit_suggestions,
    })
    context["crumb_parent"] = "Administration"
    return render(request, "accounts/system_admin/audit_log.html", context)
