from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

phone_validator = RegexValidator(
    r"^\+?[0-9][0-9 -]{6,18}[0-9]$",
    "Enter a valid phone number using digits, spaces, or dashes (for example 0917 123 4567).",
)


class AccountProfile(models.Model):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        STAFF = "staff", "CCCSP Staff"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_profile",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    phone_number = models.CharField(max_length=30, blank=True, validators=[phone_validator])
    school_name = models.CharField(max_length=150, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["student", "staff"]),
                name="account_profile_role_valid",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"
