"""Audit helpers shared by operational services and views."""

from .models import AuditLog


def record_audit(
    actor,
    module,
    record_reference,
    action,
    old_status="",
    new_status="",
    details="",
):
    """Write an immutable audit event.

    Callers are responsible for invoking this inside the same transaction as
    the business change so a rollback removes both rows together.
    """

    return AuditLog.objects.create(
        actor=actor,
        module=module,
        record_reference=record_reference,
        action=action,
        old_status=str(old_status or ""),
        new_status=str(new_status or ""),
        details=str(details or ""),
    )
