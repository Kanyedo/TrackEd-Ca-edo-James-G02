from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string

# Characters that are easy to read aloud: no 0/O or 1/I.
REFERENCE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MIN_AMOUNT = Decimal("1.00")
MAX_AMOUNT = Decimal("50000.00")
ACADEMIC_YEAR_REGEX = r"^[0-9]{4}-[0-9]{4}$"


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
    academic_year = models.CharField(
        max_length=9,
        validators=[
            RegexValidator(ACADEMIC_YEAR_REGEX, "Enter the academic year like 2026-2027.")
        ],
    )
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
            ),
            # Database-level guards (PD3): even a bug or a direct database
            # write cannot store an out-of-range amount or an unknown value.
            models.CheckConstraint(
                condition=models.Q(amount__gte=MIN_AMOUNT) & models.Q(amount__lte=MAX_AMOUNT),
                name="allowance_amount_in_range",
                violation_error_message="Amount must be between PHP 1.00 and PHP 50,000.00.",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["pending", "verifying", "approved", "ready", "released", "on_hold"]
                ),
                name="allowance_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(semester__in=["1st", "2nd", "summer"]),
                name="allowance_semester_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(academic_year__regex=ACADEMIC_YEAR_REGEX),
                name="allowance_academic_year_format",
                violation_error_message="Enter the academic year like 2026-2027.",
            ),
        ]
        indexes = [
            models.Index(fields=["status"], name="allowance_status_idx"),
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
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=AllowanceRecord.Status.values),
                name="status_update_status_valid",
            ),
        ]

    def __str__(self):
        return f"{self.record.reference_number} -> {self.get_status_display()}"
