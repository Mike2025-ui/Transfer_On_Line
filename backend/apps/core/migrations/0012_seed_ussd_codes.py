# Gestion des opérateurs: seeds UssdCode rows that exactly reproduce the
# output of the old hardcoded apps.core.serializers.build_ussd_code() for
# every (Operator, Service) pair that exists at migration time - this is
# what guarantees zero behavior change the moment 0011/0012 are applied.
# The substring logic below is a deliberate frozen copy of that old
# function's branching, NOT an import of apps.core.serializers (migrations
# must never import real app modules - only apps.get_model()).
from django.db import migrations

_TRANSFER_TEMPLATE = '*123*{numero}*{montant}#'
_DEFAULT_TEMPLATE = '*456*{montant}#'


def _is_transfer_like(service):
    service_code = (service.code or service.name).lower()
    return 'transfer' in service_code or 'transfert' in service_code


def seed_ussd_codes(apps, schema_editor):
    Operator = apps.get_model('core', 'Operator')
    Service = apps.get_model('core', 'Service')
    UssdCode = apps.get_model('core', 'UssdCode')

    services = list(Service.objects.all())
    for operator in Operator.objects.all():
        for service in services:
            template = _TRANSFER_TEMPLATE if _is_transfer_like(service) else _DEFAULT_TEMPLATE
            label = 'Transfert' if _is_transfer_like(service) else 'Autre / Général'
            UssdCode.objects.create(
                operator=operator,
                service=service,
                label=label,
                template=template,
                is_active=True,
                is_default=False,
            )
        # Operator-level fallback: reproduces the old function's `else`
        # branch for any Service that didn't exist yet at migration time.
        UssdCode.objects.create(
            operator=operator,
            service=None,
            label='Autre / Général',
            template=_DEFAULT_TEMPLATE,
            is_active=True,
            is_default=True,
        )


def reverse_seed_ussd_codes(apps, schema_editor):
    # Only remove rows this migration created (matched on the exact
    # label/template values it wrote) - never a blanket delete, since by the
    # time someone reverses this migration real dashboard-created rows may
    # already exist alongside the seed.
    UssdCode = apps.get_model('core', 'UssdCode')
    UssdCode.objects.filter(
        label__in=['Transfert', 'Autre / Général'],
        template__in=[_TRANSFER_TEMPLATE, _DEFAULT_TEMPLATE],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_ussdcode'),
    ]

    operations = [
        migrations.RunPython(seed_ussd_codes, reverse_seed_ussd_codes),
    ]
