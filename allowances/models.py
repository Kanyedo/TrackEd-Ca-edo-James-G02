from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string

# Characters that are easy to read aloud: no 0/O or 1/I.
REFERENCE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MIN_AMOUNT = Decimal("1.00")
MAX_AMOUNT = Decimal("50000.00")


class AllowanceRecord(models.Model):
    """One scholar's allowance for one academic term (BR: one record per term)."""

    class Semester(models.TextChoices):
        FIRST = "1st", "1st Semester"
        SECOND = "2nd", "2nd Semester"
        SUMMER = "summer", "Summer"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFYING = "verifying", "Under verification"
        APPROVED = "approved", "Approved"
        READY = "ready", "Ready for release"
        RELEASED = "released", "Released"
        ON_HOLD = "on_hold", "On hold"

    # Business rule: which statuses a record may move to from its current one.
    TRANSITIONS = {
        Status.PENDING: (Status.PENDING, Status.VERIFYING, Status.ON_HOLD),
        Status.VERIFYING: (Status.VERIFYING, Status.APPROVED, Status.ON_HOLD),
        Status.APPROVED: (Status.APPROVED, Status.READY, Status.ON_HOLD),
        Status.READY: (Status.READY, Status.RELEASED, Status.ON_HOLD),
        Status.ON_HOLD: (
            Status.ON_HOLD,
            Status.PENDING,
            Status.VERIFYING,
            Status.APPROVED,
            Status.READY,
        ),
        Status.RELEASED: (Status.RELEASED,),
    }
    FLOW = (
        Status.PENDING,
        Status.VERIFYING,
        Status.APPROVED,
        Status.READY,
        Status.RELEASED,
    )

    reference_number = models.CharField(max_length=20, unique=True, editable=False)
    scholar = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="allowance_records",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        editable=False,
        related_name="created_allowance_records",
    )
    academic_year = models.CharField(max_length=9)
    semester = models.CharField(max_length=10, choices=Semester.choices)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(MIN_AMOUNT, message="Amount must be at least PHP 1.00."),
            MaxValueValidator(MAX_AMOUNT, message="Amount cannot be more than PHP 50,000.00."),
        ],
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["scholar", "academic_year", "semester"],
                name="unique_allowance_per_scholar_term",
                violation_error_message=(
                    "This scholar already has an allowance record for that "
                    "academic year and semester."
                ),
            )
        ]

    def __str__(self):
        return f"{self.reference_number} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.reference_number:
            self.reference_number = self.generate_reference()
        super().save(*args, **kwargs)

    @classmethod
    def generate_reference(cls):
        year = timezone.now().year
        while True:
            reference = f"CCCSP-{year}-{get_random_string(6, REFERENCE_CHARS)}"
            if not cls.objects.filter(reference_number=reference).exists():
                return reference

    @property
    def is_locked(self):
        """Released allowances are final and cannot be edited."""
        return self.status == self.Status.RELEASED

    @property
    def can_delete(self):
        """Only records that have not entered processing may be deleted."""
        return self.status == self.Status.PENDING

    def allowed_next_statuses(self):
        return self.TRANSITIONS.get(self.status, (self.status,))

    def log_status(self, user, remarks=""):
        return StatusUpdate.objects.create(
            record=self,
            status=self.status,
            remarks=remarks,
            changed_by=user,
        )

    def progress_steps(self):
        """Steps for the progress tracker shown on the detail page."""
        effective = self.status
        if effective == self.Status.ON_HOLD:
            previous = (
                self.status_updates.exclude(status=self.Status.ON_HOLD)
                .order_by("-changed_at", "-id")
                .first()
            )
            effective = previous.status if previous else self.Status.PENDING
        labels = dict(self.Status.choices)
        current_index = list(self.FLOW).index(effective)
        steps = []
        for index, value in enumerate(self.FLOW):
            if index < current_index:
                state = "done"
            elif index == current_index:
                state = "current"
            else:
                state = "todo"
            steps.append({"value": value, "label": labels[value], "state": state})
        return steps


class StatusUpdate(models.Model):
    """History entry written every time an allowance record changes status."""

    record = models.ForeignKey(
        AllowanceRecord,
        on_delete=models.CASCADE,
        related_name="status_updates",
    )
    status = models.CharField(max_length=12, choices=AllowanceRecord.Status.choices)
    remarks = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="allowance_status_changes",
    )
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.record.reference_number} -> {self.get_status_display()}"
