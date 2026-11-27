from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

from operations.models import AuditLog


@receiver(user_login_failed)
def record_failed_login(sender, credentials, request, **kwargs):
    username = ""
    if isinstance(credentials, dict):
        username = str(credentials.get("username", "") or "")
    username = username[:150]
    AuditLog.objects.create(
        actor=None,
        module="auth",
        record_reference=username,
        action="Login failed",
        old_status="",
        new_status="failed",
        details="Sign-in failed.",
    )
