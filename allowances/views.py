from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from accounts.models import AccountProfile
from accounts.views import user_role

from .forms import AllowanceRecordForm, ReferenceLookupForm
from .models import AllowanceRecord

PAGE_SIZE = 10


def is_staff_user(user):
    return user_role(user) == AccountProfile.Role.STAFF


def staff_required(view):
    """Only logged-in CCCSP staff may use the view.

    The role is checked here on the server, so hiding a button in a template
    is never the only protection.
    """

    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_staff_user(request.user):
            messages.error(request, "Only CCCSP staff can do that.")
            return redirect("allowances:list")
        return view(request, *args, **kwargs)

    return wrapped


def visible_records(user):
    """Staff see every record; students see only their own."""
    records = AllowanceRecord.objects.select_related("scholar", "created_by")
    if is_staff_user(user):
        return records
    return records.filter(scholar=user)


@login_required
@require_GET
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
@require_GET
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
@require_http_methods(["GET", "POST"])
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
@require_http_methods(["GET", "POST"])
def record_update(request, pk):
    record = get_object_or_404(AllowanceRecord.objects.select_related("scholar"), pk=pk)
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
                # Lock the row so two staff members cannot change the same
                # record at once, then make sure nobody changed its status
                # (or released it) since this form was loaded.
                current = AllowanceRecord.objects.select_for_update().get(pk=record.pk)
                if current.status != old_status or current.is_locked:
                    messages.error(
                        request,
                        "This record was changed by someone else while you were "
                        "editing it. Please review it and try again.",
                    )
                    return redirect("allowances:detail", pk=record.pk)
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
@require_http_methods(["GET", "POST"])
def record_delete(request, pk):
    """GET shows a confirmation page; only POST (with a CSRF token) deletes."""
    record = get_object_or_404(AllowanceRecord.objects.select_related("scholar"), pk=pk)
    not_deletable = (
        "Only Pending allowances can be deleted. Set the record to On hold instead."
    )
    if not record.can_delete:
        messages.error(request, not_deletable)
        return redirect("allowances:detail", pk=record.pk)
    if request.method == "POST":
        reference = record.reference_number
        with transaction.atomic():
            # Re-check under a row lock in case the status changed meanwhile.
            current = AllowanceRecord.objects.select_for_update().get(pk=record.pk)
            if not current.can_delete:
                messages.error(request, not_deletable)
                return redirect("allowances:detail", pk=record.pk)
            current.delete()
        messages.success(request, f"Allowance record {reference} was deleted.")
        return redirect("allowances:list")
    return render(request, "allowances/confirm_delete.html", {"record": record})


@login_required
@require_http_methods(["GET", "POST"])
def record_lookup(request):
    form = ReferenceLookupForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        record = visible_records(request.user).filter(
            reference_number=form.cleaned_data["reference"]
        ).first()
        if record:
            messages.success(request, f"Showing allowance {record.reference_number}.")
            return redirect("allowances:detail", pk=record.pk)
        # Same message whether the reference does not exist or belongs to
        # another scholar, so references cannot be probed.
        messages.error(
            request, "No allowance record was found with that reference number."
        )
    return render(request, "allowances/lookup.html", {"form": form})
