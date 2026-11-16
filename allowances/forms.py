import re

from django import forms
from django.contrib.auth import get_user_model

from .models import AllowanceRecord

User = get_user_model()

ACADEMIC_YEAR_PATTERN = re.compile(r"^(\d{4})-(\d{4})$")
REFERENCE_PATTERN = re.compile(r"^CCCSP-\d{4}-[A-Z0-9]{6}$")


def student_queryset():
    return User.objects.filter(
        is_active=True,
        is_superuser=False,
        account_profile__role="student",
    )


class ScholarChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return f"{user.get_full_name() or user.username} ({user.username})"


class AllowanceRecordForm(forms.ModelForm):
    scholar = ScholarChoiceField(
        queryset=User.objects.none(),
        empty_label="Select a scholar",
        error_messages={"required": "Choose the scholar this allowance is for."},
    )

    class Meta:
        model = AllowanceRecord
        fields = ("scholar", "academic_year", "semester", "amount", "status", "remarks")
        labels = {
            "academic_year": "Academic year",
            "amount": "Allowance amount (PHP)",
            "remarks": "Remarks",
        }
        help_texts = {
            "academic_year": "Format: 2026-2027",
            "remarks": "Required when the status is set to On hold.",
        }
        widgets = {
            "academic_year": forms.TextInput(attrs={"placeholder": "2026-2027"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "1"}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scholar"].queryset = student_queryset().order_by(
            "first_name", "last_name", "username"
        )
        if self.instance.pk:
            # Editing: the scholar is fixed, and status can only follow the
            # allowed transitions from the record's current status.
            self.fields["scholar"].queryset = User.objects.filter(
                pk=self.instance.scholar_id
            )
            self.fields["scholar"].disabled = True
            allowed = self.instance.allowed_next_statuses()
            self.fields["status"].choices = [
                (value, label)
                for value, label in AllowanceRecord.Status.choices
                if value in allowed
            ]
        else:
            # New records always start as Pending.
            del self.fields["status"]
            self.fields["remarks"].help_text = ""

    def clean_academic_year(self):
        value = self.cleaned_data["academic_year"].strip()
        match = ACADEMIC_YEAR_PATTERN.match(value)
        if not match:
            raise forms.ValidationError("Enter the academic year like 2026-2027.")
        start, end = int(match.group(1)), int(match.group(2))
        if end != start + 1:
            raise forms.ValidationError(
                "The second year must be exactly one year after the first (for example 2026-2027)."
            )
        return value

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        remarks = (cleaned.get("remarks") or "").strip()
        if self.instance.pk and self.instance.is_locked:
            raise forms.ValidationError(
                "Released allowances are locked and can no longer be edited."
            )
        if status == AllowanceRecord.Status.ON_HOLD and not remarks:
            self.add_error("remarks", "Please explain why this allowance is on hold.")
        return cleaned


class ReferenceLookupForm(forms.Form):
    reference = forms.CharField(
        max_length=20,
        label="Reference number",
        error_messages={"required": "Enter a reference number."},
        widget=forms.TextInput(
            attrs={"placeholder": "CCCSP-2026-ABC123", "autocomplete": "off"}
        ),
    )

    def clean_reference(self):
        reference = self.cleaned_data["reference"].strip().upper()
        if not REFERENCE_PATTERN.match(reference):
            raise forms.ValidationError(
                "Enter a reference number like CCCSP-2026-ABC123."
            )
        return reference
