import secrets
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command, CommandError
from django.test import Client, TestCase

from accounts.roles import (
    CAPABILITIES,
    ROLE_ACCESS,
    ROLES,
    all_slugs,
    capabilities_for,
    role_by_slug,
    validate_roles,
)
from operations.modules import MODULES


class RoleDefinitionsTests(TestCase):
    def test_validate_roles_accepts_real_definitions(self):
        validate_roles()

    def test_role_access_keys_exist_in_roles(self):
        role_slugs = set(all_slugs())
        self.assertTrue(set(ROLE_ACCESS).issubset(role_slugs))

    def test_role_access_module_keys_exist_in_registry(self):
        module_keys = {module["key"] for module in MODULES}
        access_keys = {
            module_key
            for role_access in ROLE_ACCESS.values()
            for module_key in role_access
        }
        self.assertTrue(access_keys.issubset(module_keys))

    def test_role_capabilities_are_declared(self):
        declared = set(CAPABILITIES)
        used = {
            capability
            for role in ROLES
            for capability in role["capabilities"]
        }
        self.assertTrue(used.issubset(declared))

    def test_role_helpers_return_ordered_data_and_empty_unknowns(self):
        self.assertEqual(all_slugs(), [role["slug"] for role in ROLES])
        self.assertIs(role_by_slug("system-administrator"), ROLES[0])
        self.assertIsNone(role_by_slug("unknown-role"))
        self.assertEqual(
            capabilities_for("system-administrator"),
            ("manage_users", "view_audit"),
        )
        self.assertEqual(capabilities_for("unknown-role"), ())


class SyncRolesCommandTests(TestCase):
    def test_sync_roles_is_idempotent(self):
        first_output = StringIO()
        call_command("sync_roles", stdout=first_output)
        self.assertEqual(Group.objects.count(), 10)
        self.assertIn("created=10, existing=0", first_output.getvalue())

        second_output = StringIO()
        call_command("sync_roles", stdout=second_output)
        self.assertEqual(Group.objects.count(), 10)
        self.assertIn("created=0, existing=10", second_output.getvalue())

    def test_existing_group_member_is_preserved(self):
        user_model = get_user_model()
        role_slug = all_slugs()[0]
        group = Group.objects.create(name=role_slug)
        member = user_model._default_manager.create_user(username="role_member")
        member.groups.add(group)

        call_command("sync_roles", stdout=StringIO())

        self.assertTrue(Group.objects.filter(pk=group.pk, name=role_slug).exists())
        self.assertTrue(member.groups.filter(pk=group.pk).exists())
        self.assertEqual(Group.objects.count(), 10)

    def test_sync_roles_dry_run_does_not_create_groups(self):
        output = StringIO()
        call_command("sync_roles", dry_run=True, stdout=output)
        self.assertEqual(Group.objects.count(), 0)
        self.assertIn("would_create=10", output.getvalue())

    def test_validation_error_creates_no_groups(self):
        output = StringIO()
        errors = StringIO()
        with patch(
            "accounts.management.commands.sync_roles.validate_roles",
            side_effect=ValueError("invalid test definitions"),
        ):
            with self.assertRaises(CommandError):
                call_command("sync_roles", stdout=output, stderr=errors)

        self.assertEqual(Group.objects.count(), 0)


class SyncRoleUsersCommandTests(TestCase):
    def test_dry_run_does_not_create_users(self):
        call_command("sync_roles", stdout=StringIO())
        output = StringIO()

        call_command(
            "sync_role_users",
            password=secrets.token_urlsafe(24),
            dry_run=True,
            stdout=output,
        )

        self.assertEqual(get_user_model()._default_manager.count(), 0)
        self.assertIn("would_create=10", output.getvalue())

    def test_missing_password_reports_usage_and_creates_no_users(self):
        output = StringIO()
        errors = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "sync_role_users",
                stdout=output,
                stderr=errors,
            )

        self.assertIn("Usage: python manage.py sync_role_users", errors.getvalue())
        self.assertEqual(get_user_model()._default_manager.count(), 0)

    def test_user_has_exactly_its_role_group(self):
        call_command("sync_roles", stdout=StringIO())
        password = secrets.token_urlsafe(24)
        output = StringIO()

        call_command("sync_role_users", password=password, stdout=output)

        username = "test_enduser_maintenance_lead"
        user = get_user_model()._default_manager.get(username=username)
        self.assertEqual(list(user.groups.values_list("name", flat=True)), [
            "enduser-maintenance-lead",
        ])
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(password))
        self.assertNotIn(password, output.getvalue())

    def test_existing_user_keeps_password_and_gets_only_its_role(self):
        call_command("sync_roles", stdout=StringIO())
        user_model = get_user_model()
        username = "test_enduser_maintenance_lead"
        password = secrets.token_urlsafe(24)
        user = user_model._default_manager.create_user(
            username=username,
            password=password,
            is_staff=False,
            is_superuser=False,
        )
        user.groups.add(Group.objects.get(name="pr-creator"))

        call_command(
            "sync_role_users",
            password=secrets.token_urlsafe(24),
            stdout=StringIO(),
        )

        user.refresh_from_db()
        self.assertTrue(user.check_password(password))
        self.assertEqual(
            list(user.groups.values_list("name", flat=True)),
            ["enduser-maintenance-lead"],
        )

    def test_role_user_signs_in_and_frontend_routes_still_load(self):
        call_command("sync_roles", stdout=StringIO())
        password = secrets.token_urlsafe(24)
        call_command("sync_role_users", password=password, stdout=StringIO())
        client = Client()

        self.assertTrue(
            client.login(
                username="test_enduser_maintenance_lead",
                password=password,
            )
        )
        dashboard = client.get("/")
        records = client.get("/records/needs/")

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(records.status_code, 200)
        self.assertContains(dashboard, "Not connected")
        self.assertContains(records, "Not connected")
