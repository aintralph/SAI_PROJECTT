from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from accounts.roles import ROLES, validate_roles


class Command(BaseCommand):
    help = "Create demo users and assign each user to its matching role group."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            help="Password to set on newly created demo users.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report changes without creating or updating users.",
        )

    def handle(self, *args, password=None, dry_run=False, **options):
        if not password:
            self.stderr.write(
                "Usage: python manage.py sync_role_users "
                "--password <password> [--dry-run]"
            )
            raise CommandError("--password is required.")

        try:
            validate_roles()
        except ValueError as error:
            raise CommandError("Role validation failed: %s" % error) from error

        groups = {
            group.name: group
            for group in Group.objects.filter(
                name__in=[role["slug"] for role in ROLES]
            )
        }
        missing_groups = [
            role["slug"] for role in ROLES if role["slug"] not in groups
        ]
        if missing_groups:
            raise CommandError(
                "Run sync_roles first; missing groups: %s"
                % ", ".join(missing_groups)
            )

        User = get_user_model()
        created_count = 0
        existing_count = 0
        would_create_count = 0

        for role in ROLES:
            slug = role["slug"]
            username = "test_" + slug.replace("-", "_")
            user = User._default_manager.filter(username=username).first()

            if dry_run:
                if user is None:
                    would_create_count += 1
                    result = "would create"
                else:
                    existing_count += 1
                    result = "existing"
            else:
                user, created = User._default_manager.get_or_create(
                    username=username,
                    defaults={"is_staff": False, "is_superuser": False},
                )
                if created:
                    user.set_password(password)
                    user.save(update_fields=["password"])
                    created_count += 1
                    result = "created"
                else:
                    existing_count += 1
                    result = "existing"

                update_fields = []
                if user.is_staff:
                    user.is_staff = False
                    update_fields.append("is_staff")
                if user.is_superuser:
                    user.is_superuser = False
                    update_fields.append("is_superuser")
                if update_fields:
                    user.save(update_fields=update_fields)
                user.groups.set([groups[slug]])

            self.stdout.write("%s %s: %s" % (username, slug, result))

        summary = "total=%d, created=%d, existing=%d" % (
            len(ROLES),
            created_count,
            existing_count,
        )
        if dry_run:
            summary += ", would_create=%d" % would_create_count
        self.stdout.write(summary)
