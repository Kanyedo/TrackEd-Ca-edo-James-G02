from django.db.models import Count

from .models import AllowanceRecord


def student_summary(user):
    """Numbers shown on the student dashboard card."""
    records = AllowanceRecord.objects.filter(scholar=user)
    return {
        "total": records.count(),
        "latest": records.order_by("-updated_at", "-id").first(),
    }


def staff_summary():
    """Per-status counts shown on the staff dashboard card."""
    counts = dict(
        AllowanceRecord.objects.order_by().values_list("status").annotate(n=Count("id"))
    )
    rows = [
        {"value": value, "label": label, "count": counts.get(value, 0)}
        for value, label in AllowanceRecord.Status.choices
    ]
    return {"total": sum(counts.values()), "rows": rows}
