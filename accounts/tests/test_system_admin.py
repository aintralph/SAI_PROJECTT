from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_login_failed
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from operations.models import AuditLog


class SystemAdministratorTests(TestCase):
    def setUp(self):
        call_command("sync_roles", stdout=__import__("io").StringIO())
        self.User = get_user_model()
        self.sysadmin_group = Group.objects.get(name="system-administrator")
        self.sysadmin = self.User.objects.create_user(
            username="sysadmin",
            password="SafeTestPassword123!",
            first_name="System",
            last_name="Admin",
        )
        self.sysadmin.groups.add(self.sysadmin_group)

    def test_system_administrator_login_redirect(self):
        client = self.client
        self.assertTrue(client.login(username="sysadmin", password="SafeTestPassword123!"))
        response = client.get(reverse("root"))
        self.assertRedirects(response, reverse("system_admin_dashboard"), fetch_redirect_response=False)

    def test_superuser_login_redirects_to_admin(self):
        superuser = self.User.objects.create_superuser(
            username="root",
            email="root@example.com",
            password="SafeTestPassword123!",
        )
        self.assertTrue(self.client.login(username="root", password="SafeTestPassword123!"))
        response = self.client.get(reverse("root"))
        self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)

    def test_normal_user_cannot_open_administration_routes(self):
        normal = self.User.objects.create_user(username="normal", password="SafeTestPassword123!")
        self.assertTrue(self.client.login(username="normal", password="SafeTestPassword123!"))
        for name in (
            "system_admin_dashboard",
            "system_admin_accounts",
            "system_admin_role_groups",
            "system_admin_audit_log",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("system_admin_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_dashboard_uses_real_counts_and_empty_data(self):
        self.client.force_login(self.sysadmin)
        response = self.client.get(reverse("system_admin_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Active accounts")
        self.assertContains(response, "Role groups")
        self.assertEqual(response.context["metrics"][0]["value"], 1)

    def test_account_creation_hashes_password_assigns_role_and_audits(self):
        self.client.force_login(self.sysadmin)
        role = "pr-creator"
        response = self.client.post(reverse("system_admin_account_create"), {
            "username": "created_user",
            "first_name": "Created",
            "last_name": "User",
            "email": "created@example.com",
            "password1": "SafeCreatePassword123!",
            "password2": "SafeCreatePassword123!",
            "is_active": "on",
            "role": role,
            "department": "",
            "employee_id": "",
        })
        self.assertRedirects(response, reverse("system_admin_accounts"), fetch_redirect_response=False)
        account = self.User.objects.get(username="created_user")
        self.assertFalse(account.is_staff)
        self.assertFalse(account.is_superuser)
        self.assertTrue(account.check_password("SafeCreatePassword123!"))
        self.assertNotEqual(account.password, "SafeCreatePassword123!")
        self.assertTrue(account.groups.filter(name=role).exists())
        self.assertTrue(AuditLog.objects.filter(module="accounts", record_reference="created_user", action="Account created").exists())

    def test_unknown_role_is_rejected(self):
        self.client.force_login(self.sysadmin)
        response = self.client.post(reverse("system_admin_account_create"), {
            "username": "bad_role",
            "password1": "SafeCreatePassword123!",
            "password2": "SafeCreatePassword123!",
            "is_active": "on",
            "role": "arbitrary-role",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.User.objects.filter(username="bad_role").exists())

    def test_non_superuser_cannot_edit_staff_or_superuser(self):
        staff = self.User.objects.create_user(username="staff", password="SafeTestPassword123!", is_staff=True)
        superuser = self.User.objects.create_superuser(username="root2", email="root2@example.com", password="SafeTestPassword123!")
        self.client.force_login(self.sysadmin)
        self.assertEqual(self.client.get(reverse("system_admin_account_edit", args=[staff.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("system_admin_account_edit", args=[superuser.pk])).status_code, 403)

    def test_user_cannot_deactivate_self(self):
        self.client.force_login(self.sysadmin)
        response = self.client.post(reverse("system_admin_account_edit", args=[self.sysadmin.pk]), {
            "first_name": "System",
            "last_name": "Admin",
            "email": "",
            "is_active": "",
            "role": "system-administrator",
            "department": "",
            "employee_id": "",
        })
        self.assertEqual(response.status_code, 200)
        self.sysadmin.refresh_from_db()
        self.assertTrue(self.sysadmin.is_active)
        self.assertContains(response, "cannot deactivate")

    def test_account_role_and_activation_changes_are_audited(self):
        account = self.User.objects.create_user(username="change_me", password="SafeTestPassword123!")
        pr = Group.objects.get(name="pr-creator")
        account.groups.add(pr)
        self.client.force_login(self.sysadmin)
        response = self.client.post(reverse("system_admin_account_edit", args=[account.pk]), {
            "first_name": "Changed",
            "last_name": "Account",
            "email": "changed@example.com",
            "is_active": "",
            "role": "odm",
            "department": "",
            "employee_id": "",
        })
        self.assertRedirects(response, reverse("system_admin_accounts"), fetch_redirect_response=False)
        account.refresh_from_db()
        self.assertFalse(account.is_active)
        self.assertTrue(account.groups.filter(name="odm").exists())
        self.assertFalse(account.groups.filter(name="pr-creator").exists())
        self.assertTrue(AuditLog.objects.filter(record_reference="change_me", action="Role changed").exists())
        self.assertTrue(AuditLog.objects.filter(record_reference="change_me", action="Account activation changed").exists())

    def test_failed_login_is_sanitized_and_password_is_not_stored(self):
        password = "NeverStoreThisPassword!"
        user_login_failed.send(
            sender=self.__class__,
            credentials={"username": "missing_user", "password": password},
            request=None,
        )
        entry = AuditLog.objects.get(module="auth", action="Login failed")
        self.assertEqual(entry.record_reference, "missing_user")
        self.assertNotIn(password, entry.details)
        self.assertNotIn(password, str(entry))

    def test_removed_routes_and_sidebar_links_are_unavailable(self):
        self.client.force_login(self.sysadmin)
        self.assertEqual(self.client.get("/accounts/access/").status_code, 404)
        self.assertEqual(self.client.get("/accounts/").status_code, 404)
        dashboard = self.client.get(reverse("system_admin_dashboard"))
        self.assertNotContains(dashboard, "Access map")
        self.assertNotContains(dashboard, "My workspaces")

    def test_empty_administration_screens_render(self):
        self.User.objects.filter(username="sysadmin").delete()
        superuser = self.User.objects.create_superuser(username="root", email="root@example.com", password="SafeTestPassword123!")
        self.client.force_login(superuser)
        self.assertContains(self.client.get(reverse("system_admin_accounts")), "root", status_code=200)
        self.assertContains(self.client.get(reverse("system_admin_role_groups")), "Code-defined roles", status_code=200)
        self.assertContains(self.client.get(reverse("system_admin_audit_log")), "No audit entries", status_code=200)

    def test_account_list_search_and_filters_preserve_state(self):
        account = self.User.objects.create_user(
            username="search_target",
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            is_active=False,
        )
        account.groups.add(Group.objects.get(name="pr-creator"))
        self.client.force_login(self.sysadmin)

        response = self.client.get(reverse("system_admin_accounts"), {
            "q": "Ada",
            "status": "inactive",
            "role": "pr-creator",
        })

        self.assertContains(response, "search_target")
        self.assertContains(response, "Ada Lovelace")
        self.assertContains(response, 'name="q" value="Ada"')
        self.assertContains(response, "Manage account")
        self.assertContains(response, "Inactive")
        self.assertContains(response, "PR Creator")

    def test_account_list_formats_missing_profile_and_suggestions(self):
        account = self.User.objects.create_user(username="long_no_profile_account")
        self.client.force_login(self.sysadmin)

        response = self.client.get(reverse("system_admin_accounts"))

        self.assertContains(response, "No profile details")
        self.assertContains(response, "No recognized role")
        self.assertContains(response, 'aria-autocomplete="list"')
        self.assertContains(response, 'role="listbox"')
        self.assertContains(response, 'data-value="long_no_profile_account"')
        self.assertContains(response, "Manage account for long_no_profile_account")
        self.assertContains(response, 'data-custom-select')
        self.assertContains(response, 'name="status"')
        self.assertContains(response, 'name="role"')

    def test_audit_log_search_suggestions_use_visible_values(self):
        AuditLog.objects.create(
            actor=self.sysadmin,
            module="accounts",
            record_reference="audit_actor",
            action="Account created",
        )
        self.client.force_login(self.sysadmin)

        response = self.client.get(reverse("system_admin_audit_log"))

        self.assertContains(response, 'data-search-combobox')
        self.assertContains(response, 'aria-controls="audit-suggestions"')
        self.assertContains(response, 'data-value="audit_actor"')

    def test_profile_requires_authentication_and_shows_only_signed_in_user(self):
        anonymous = self.client.get(reverse("profile"))
        self.assertEqual(anonymous.status_code, 302)
        self.client.force_login(self.sysadmin)
        response = self.client.get(reverse("profile") + "?user_id=other")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sysadmin")
