from django.contrib import admin

from .models import AllowanceRecord, StatusUpdate


class StatusUpdateInline(admin.TabularInline):
    model = StatusUpdate
    extra = 0
    readonly_fields = ("status", "remarks", "changed_by", "changed_at")
    can_delete = False


@admin.register(AllowanceRecord)
class AllowanceRecordAdmin(admin.ModelAdmin):
    list_display = ("reference_number", "scholar", "academic_year", "semester", "amount", "status")
    list_filter = ("status", "semester", "academic_year")
    search_fields = ("reference_number", "scholar__username", "scholar__first_name", "scholar__last_name")
    readonly_fields = ("reference_number", "created_by", "created_at", "updated_at")
    inlines = (StatusUpdateInline,)
