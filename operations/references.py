"""Concurrency-safe reference generation for operational records.

References use the project prefix, the current year, and a zero-padded
sequence. A dedicated counter row is locked while the next value is issued so
two concurrent requests cannot receive the same reference.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ReferenceCounter


def next_reference(prefix, *, max_attempts=5):
    prefix = (prefix or "").strip().upper()
    if not prefix.isalnum() or not (2 <= len(prefix) <= 10):
        raise ValueError("Reference prefix must be 2-10 alphanumeric characters.")

    year = timezone.now().year
    for _attempt in range(max_attempts):
        try:
            with transaction.atomic():
                counter, created = ReferenceCounter.objects.get_or_create(
                    prefix=prefix,
                    year=year,
                    defaults={"last_value": 1},
                )
        except IntegrityError:
            # Another transaction created the counter between our read and
            # write. Retry and lock the existing row instead.
            continue

        if created:
            return f"{prefix}-{year}-{counter.last_value:06d}"

        with transaction.atomic():
            counter = ReferenceCounter.objects.select_for_update().get(pk=counter.pk)
            counter.last_value += 1
            counter.save(update_fields=["last_value"])
            return f"{prefix}-{year}-{counter.last_value:06d}"

    raise RuntimeError("Unable to allocate a unique reference after retries.")
