from django.contrib import admin
from .models import Device, Service, Operator, Gateway, Payment, Transaction, Refund, Settings, AdminProfile, AuditLog

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('uid', 'primary_phone', 'created_at')

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')

@admin.register(Operator)
class OperatorAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')

@admin.register(Gateway)
class GatewayAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'is_active', 'last_heartbeat')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('method', 'reference', 'amount', 'status', 'created_at')

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('reference', 'amount', 'status', 'payment_method', 'gateway', 'created_at')
    list_filter = ('status', 'payment_method', 'service', 'gateway')
    search_fields = ('reference', 'phone_number')

@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'status', 'created_at')
    list_filter = ('status',)

@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ('key', 'value')

@admin.register(AdminProfile)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('admin', 'action', 'timestamp')