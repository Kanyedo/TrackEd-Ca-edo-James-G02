from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.db import transaction

from .models import AccountProfile


class AccountProfileInline(admin.StackedInline):
    model = AccountProfile
    can_delete = False
    extra = 0


def _set_role(modeladmin, request, queryset, role):
    """Assign ``role`` to every selected user (ISS-03)."""
    with transaction.atomic():
        for user in queryset:
            profile, _ = AccountProfile.objects.get_or_create(user=user)
            profile.role = role
            profile.save(update_fields=["role"])
    label = AccountProfile.Role(role).label
    modeladmin.message_user(
        request,
        f"{queryset.count()} account(s) set to {label}.",
        messages.SUCCESS,
    )


@admin.action(description="Set selected accounts to CCCSP Staff")
def make_staff(modeladmin, request, queryset):
    _set_role(modeladmin, request, queryset, AccountProfile.Role.STAFF)


@admin.action(description="Set selected accounts to Student")
def make_student(modeladmin, request, queryset):
    _set_role(modeladmin, request, queryset, AccountProfile.Role.STUDENT)


class AccountUserAdmin(UserAdmin):
    inlines = (AccountProfileInline,)
    list_display = ("username", "email", "first_name", "last_name", "role", "is_active")
    list_filter = ("account_profile__role", "is_active", "is_superuser")
    list_select_related = ("account_profile",)
    actions = (make_staff, make_student)

    @admin.display(description="Role", ordering="account_profile__role")
    def role(self, user):
        profile = getattr(user, "account_profile", None)
        return profile.get_role_display() if profile else "-"


admin.site.unregister(get_user_model())
admin.site.register(get_user_model(), AccountUserAdmin)
