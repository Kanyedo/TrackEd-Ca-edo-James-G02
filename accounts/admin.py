from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import AccountProfile


class AccountProfileInline(admin.StackedInline):
    model = AccountProfile
    can_delete = False
    extra = 0


class AccountUserAdmin(UserAdmin):
    inlines = (AccountProfileInline,)


admin.site.unregister(get_user_model())
admin.site.register(get_user_model(), AccountUserAdmin)
