from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from allowances.summary import staff_summary, student_summary

from .forms import ProfileDetailsForm, ProfileUserForm, RegistrationForm
from .models import AccountProfile


def user_role(user):
    if user.is_superuser:
        return AccountProfile.Role.STAFF
    profile = AccountProfile.objects.filter(user=user).first()
    return profile.role if profile else AccountProfile.Role.STUDENT


def dashboard_url(user):
    if user_role(user) == AccountProfile.Role.STAFF:
        return "accounts:staff_dashboard"
    return "accounts:student_dashboard"


def role_required(role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if user_role(request.user) != role:
                messages.error(request, "You do not have permission to view that dashboard.")
                return redirect(dashboard_url(request.user))
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def register(request):
    if request.user.is_authenticated:
        return redirect(dashboard_url(request.user))
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your student account has been created. You can now log in.")
        return redirect("accounts:login")
    return render(request, "accounts/register.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect(dashboard_url(request.user))
    form = AuthenticationForm(
        request,
        data=request.POST if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        messages.success(request, "Welcome back.")
        return redirect(dashboard_url(user))
    if request.method == "POST":
        messages.error(request, "The username or password you entered is incorrect.")
    return render(request, "accounts/login.html", {"form": form})


@login_required
@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("accounts:login")


@login_required
def dashboard(request):
    return redirect(dashboard_url(request.user))


@role_required(AccountProfile.Role.STUDENT)
def student_dashboard(request):
    return render(
        request,
        "accounts/student_dashboard.html",
        {"allowance_summary": student_summary(request.user)},
    )


@role_required(AccountProfile.Role.STAFF)
def staff_dashboard(request):
    return render(
        request,
        "accounts/staff_dashboard.html",
        {"allowance_summary": staff_summary()},
    )


@login_required
def profile(request):
    profile_record, _ = AccountProfile.objects.get_or_create(user=request.user)
    post_data = request.POST if request.method == "POST" else None
    user_form = ProfileUserForm(post_data, instance=request.user, prefix="user")
    details_form = ProfileDetailsForm(
        post_data,
        instance=profile_record,
        prefix="profile",
    )
    if request.method == "POST":
        if user_form.is_valid() and details_form.is_valid():
            with transaction.atomic():
                user_form.save()
                details_form.save()
            messages.success(request, "Your profile has been updated.")
            return redirect("accounts:profile")
        messages.error(request, "Please correct the errors below.")
    return render(
        request,
        "accounts/profile.html",
        {"user_form": user_form, "details_form": details_form},
    )
