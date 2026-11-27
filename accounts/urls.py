from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.ProjectLoginView.as_view(), name="login"),
    path("profile/", views.profile, name="profile"),
    path("administration/", views.system_admin_dashboard, name="system_admin_dashboard"),
    path("administration/accounts/", views.system_admin_accounts, name="system_admin_accounts"),
    path("administration/accounts/create/", views.system_admin_account_create, name="system_admin_account_create"),
    path("administration/accounts/<int:user_id>/edit/", views.system_admin_account_edit, name="system_admin_account_edit"),
    path("administration/roles/", views.system_admin_role_groups, name="system_admin_role_groups"),
    path("administration/audit/", views.system_admin_audit_log, name="system_admin_audit_log"),
    path(
        "password/change/",
        views.ProjectPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path("denied/", views.access_denied, name="access_denied"),
]
