from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import AccountProfile
from accounts.views import user_role

from .forms import AllowanceRecordForm, ReferenceLookupForm
from .models import AllowanceRecord

PAGE_SIZE = 10


def is_staff_user(user):
    return user_role(user) == AccountProfile.Role.STAFF


def staff_required(view):
    """Only logged-in CCCSP staff may use the view."""

    def wrapped(request, *args, **kwargs):
        if not is_staff_user(request.user):
            messages.error(request, "Only CCCSP staff can do that.")
            return redirect("allowances:list")
        return view(request, *args, **kwargs)

    wrapped.__name__ = view.__name__
    wrapped.__doc__ = view.__doc__
    return login_required(wrapped)


def visible_records(user):
    """Staff see every record; students see only their own."""
    records = AllowanceRecord.objects.select_related("scholar", "created_by")
    if is_staff_user(user):
        return records
    return records.filter(scholar=user)


@login_required
def record_list(request):
    staff = is_staff_user(request.user)
    records = visible_records(request.user)

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if status in AllowanceRecord.Status.values:
        records = records.filter(status=status)
    else:
        status = ""
    if query:
        match = Q(reference_number__icontains=query) | Q(academic_year__icontains=query)
        if staff:
            match |= (
                Q(scholar__username__icontains=query)
                | Q(scholar__first_name__icontains=query)
                | Q(scholar__last_name__icontains=query)
            )
        records = records.filter(match)

    page_obj = Paginator(records, PAGE_SIZE).get_page(request.GET.get("page"))
    params = {key: value for key, value in (("q", query), ("status", status)) if value}
    return render(
        request,
        "allowances/list.html",
        {
            "page_obj": page_obj,
            "q": query,
            "status": status,
            "statuses": AllowanceRecord.Status.choices,
            "is_staff": staff,
            "querystring": urlencode(params),
        },
    )


@login_required
def record_detail(request, pk):
    # Students asking for someone else's record get a 404, not a 403.
    record = get_object_or_404(visible_records(request.user), pk=pk)
    return render(
        request,
        "allowances/detail.html",
        {
            "record": record,
            "history": record.status_updates.select_related("changed_by"),
            "steps": record.progress_steps(),
            "is_staff": is_staff_user(request.user),
        },
    )


@staff_required
def record_create(request):
    form = AllowanceRecordForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if form.is_valid():
            try:
                with transaction.atomic():
                    record = form.save(commit=False)
                    record.created_by = request.user
                    record.status = AllowanceRecord.Status.PENDING
                    record.save()
                    record.log_status(request.user, "Allowance record created.")
            except IntegrityError:
                form.add_error(
                    None,
                    "This scholar already has an allowance record for that academic year and semester.",
                )
            else:
                messages.success(
                    request,
                    f"Allowance record {record.reference_number} was created.",
                )
                return redirect("allowances:detail", pk=record.pk)
        messages.error(request, "Please correct the errors below.")
    return render(request, "allowances/form.html", {"form": form, "mode": "create"})


@staff_required
def record_update(request, pk):
    record = get_object_or_404(AllowanceRecord, pk=pk)
    if record.is_locked:
        messages.error(
            request, "Released allowances are locked and can no longer be edited."
        )
        return redirect("allowances:detail", pk=record.pk)

    old_status = record.status
    form = AllowanceRecordForm(
        request.POST if request.method == "POST" else None, instance=record
    )
    if request.method == "POST":
        if form.is_valid():
            with transaction.atomic():
                updated = form.save()
                if updated.status != old_status:
                    updated.log_status(request.user, updated.remarks)
            messages.success(
                request, f"Allowance record {updated.reference_number} was updated."
            )
            return redirect("allowances:detail", pk=updated.pk)
        messages.error(request, "Please correct the errors below.")
    return render(
        request,
        "allowances/form.html",
        {"form": form, "mode": "update", "record": record},
    )


@staff_required
def record_delete(request, pk):
    record = get_object_or_404(AllowanceRecord, pk=pk)
    if not record.can_delete:
        messages.error(
            request,
            "Only Pending allowances can be deleted. Set the record to On hold instead.",
        )
        return redirect("allowances:detail", pk=record.pk)
    if request.method == "POST":
        reference = record.reference_number
        record.delete()
        messages.success(request, f"Allowance record {reference} was deleted.")
        return redirect("allowances:list")
    return render(request, "allowances/confirm_delete.html", {"record": record})


@login_required
def record_lookup(request):
    form = ReferenceLookupForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        record = visible_records(request.user).filter(
            reference_number=form.cleaned_data["reference"]
        ).first()
        if record:
            return redirect("allowances:detail", pk=record.pk)
        messages.error(
            request, "No allowance record was found with that reference number."
        )
    return render(request, "allowances/lookup.html", {"form": form})
