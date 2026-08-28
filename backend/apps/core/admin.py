from django import forms
from django.contrib import admin
from .models import Device, Service, Operator, Gateway, Payment, Transaction, TransactionAttempt, TransactionEvent, Refund, Settings, AdminProfile, AuditLog, UssdCode, UssdStep, UssdStepField

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
    list_display = ('name', 'status', 'is_active', 'last_heartbeat', 'api_key_hash')
    readonly_fields = ('api_key_hash',)
    actions = ['generate_new_secret']

    @admin.action(description='Générer un nouveau secret pour la Gateway sélectionnée')
    def generate_new_secret(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Sélectionnez exactement une Gateway à la fois.', level='error')
            return
        gateway = queryset.first()
        secret = gateway.generate_secret()
        self.message_user(
            request,
            f'Nouveau secret pour "{gateway.name}" : {secret} '
            f'— copiez-le maintenant, il ne sera plus jamais affiché.',
            level='warning',
        )

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('method', 'reference', 'provider_transaction_id', 'amount', 'status', 'created_at')
    list_filter = ('method', 'status')
    search_fields = ('reference', 'provider_transaction_id')

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('reference', 'amount', 'status', 'payment_method', 'gateway', 'created_at')
    list_filter = ('status', 'payment_method', 'service', 'gateway')
    search_fields = ('reference', 'phone_number')

@admin.register(TransactionAttempt)
class TransactionAttemptAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'attempt_number', 'gateway_sim', 'status', 'failure_reason', 'created_at')
    list_filter = ('status', 'failure_reason')

@admin.register(TransactionEvent)
class TransactionEventAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'event_type', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('transaction__reference',)

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


# Phase A (moteur USSD interactif) : éditeur de scénario, additif à
# apps/dashboard/ qui reste seul propriétaire du CRUD label/template/
# is_active/aperçu de UssdCode - cet enregistrement Admin natif n'existait
# pas avant et ne remplace rien.

class UssdStepFieldInlineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        orders = []
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            orders.append(form.cleaned_data['order'])
        if len(orders) != len(set(orders)):
            raise forms.ValidationError('Deux champs ne peuvent pas avoir le même ordre.')
        # Bloque FINAL_FIELD + champ AVANT l'enregistrement (le clean() du
        # modèle UssdStepField ne peut pas encore le voir : step et ses
        # nouveaux champs sont soumis ensemble, step n'a pas toujours de pk).
        if self.instance.step_type == 'FINAL_FIELD' and orders:
            raise forms.ValidationError('Une étape FINAL_FIELD ne peut recevoir aucun champ.')


class UssdStepFieldInline(admin.TabularInline):
    model = UssdStepField
    formset = UssdStepFieldInlineFormSet
    extra = 0


@admin.register(UssdStep)
class UssdStepAdmin(admin.ModelAdmin):
    list_display = ('ussd_code', 'order', 'step_type', 'name')
    list_filter = ('step_type', 'ussd_code__operator')
    inlines = [UssdStepFieldInline]


class UssdStepInlineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        orders = [
            form.cleaned_data['order']
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE')
        ]
        if len(orders) != len(set(orders)):
            raise forms.ValidationError('Deux étapes ne peuvent pas avoir le même ordre.')


class UssdStepInline(admin.TabularInline):
    model = UssdStep
    formset = UssdStepInlineFormSet
    fields = ('order', 'step_type', 'name')
    extra = 0
    show_change_link = True


@admin.register(UssdCode)
class UssdCodeAdmin(admin.ModelAdmin):
    list_display = ('operator', 'service', 'label', 'template', 'is_active')
    list_filter = ('operator', 'is_active')
    inlines = [UssdStepInline]
