from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from accounts.roles import ROLES, validate_roles


class Command(BaseCommand):
    help = "Create missing Sample Project role groups without changing existing groups."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report changes without creating groups.",
        )

    def handle(self, *args, dry_run=False, **options):
        try:
            validate_roles()
        except ValueError as error:
            raise CommandError("Role validation failed: %s" % error) from error

        created_count = 0
        existing_count = 0
        would_create_count = 0

        for role in ROLES:
            slug = role["slug"]
            if dry_run:
                exists = Group.objects.filter(name=slug).exists()
                if exists:
                    existing_count += 1
                    result = "existing"
                else:
                    would_create_count += 1
                    result = "would create"
            else:
                _, created = Group.objects.get_or_create(name=slug)
                if created:
                    created_count += 1
                    result = "created"
                else:
                    existing_count += 1
                    result = "existing"
            self.stdout.write("%s: %s" % (slug, result))

        summary = "total=%d, created=%d, existing=%d" % (
            len(ROLES),
            created_count,
            existing_count,
        )
        if dry_run:
            summary += ", would_create=%d" % would_create_count
        self.stdout.write(summary)
