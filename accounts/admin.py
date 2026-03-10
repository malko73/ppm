from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuthEventLog, CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('email', 'username', 'is_staff', 'is_active')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('username', 'first_name', 'last_name')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'username', 'password1', 'password2', 'is_staff', 'is_active'),
            },
        ),
    )


@admin.register(AuthEventLog)
class AuthEventLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'event', 'user', 'identifier', 'ip_address', 'reason', 'request_id')
    list_filter = ('event', 'reason', 'created_at')
    search_fields = ('identifier', 'request_id', 'ip_address', 'user__email')
    readonly_fields = (
        'created_at',
        'event',
        'user',
        'identifier',
        'ip_address',
        'user_agent',
        'request_id',
        'reason',
        'previous_hash',
        'payload_hash',
        'entry_hash',
    )
    ordering = ('-id',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
