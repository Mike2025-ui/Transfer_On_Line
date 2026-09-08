from django.db import migrations


CANONICAL = {
    'voix': 'Appels (Pass voix)',
    'internet': 'Internet (Pass data)',
    'credit': 'Crédit (communication)',
    'sms': 'SMS (Pass SMS)',
}

ALIASES = {
    'apple': 'voix',
    'appel': 'voix',
    'appels': 'voix',
    'voice': 'voix',
    'subscription': 'internet',
    'data': 'internet',
    'transfert_unite': 'credit',
    'credit_communication': 'credit',
}


def normalize(value):
    return ''.join(char for char in value.lower().strip() if char.isalnum())


def canonical_code(service):
    code = normalize(service.code)
    name = normalize(service.name)
    if code in CANONICAL:
        return code
    if code in ALIASES:
        return ALIASES[code]
    for key, label in CANONICAL.items():
        if normalize(label) in (code, name) or key in code or key in name:
            return key
    return None


def organize_catalog(apps, schema_editor):
    Service = apps.get_model('core', 'Service')
    UssdCode = apps.get_model('core', 'UssdCode')
    Transaction = apps.get_model('core', 'Transaction')

    services_by_code = {}
    for code, name in CANONICAL.items():
        service = Service.objects.filter(code=code).order_by('id').first()
        if service is None:
            service = Service.objects.create(code=code, name=name, is_active=True)
        elif service.name != name or not service.is_active:
            service.name = name
            service.is_active = True
            service.save(update_fields=['name', 'is_active'])
        services_by_code[code] = service

    for service in Service.objects.exclude(code__in=CANONICAL):
        target_code = canonical_code(service)
        if target_code is None:
            service.is_active = False
            service.save(update_fields=['is_active'])
            continue

        target = services_by_code[target_code]
        # Preserve all existing history by moving foreign keys before retiring
        # the legacy service row.
        UssdCode.objects.filter(service_id=service.id).update(service_id=target.id)
        Transaction.objects.filter(service_id=service.id).update(service_id=target.id)
        service.is_active = False
        service.save(update_fields=['is_active'])

    # If two active USSD rows now resolve to the same operator/service/amount,
    # keep the oldest configuration active and retire the duplicate. This is
    # deterministic and avoids destroying an operator's configured code.
    seen = set()
    for code in UssdCode.objects.filter(is_active=True).order_by('operator_id', 'service_id', 'amount', 'id'):
        key = (code.operator_id, code.service_id, code.amount)
        if key in seen:
            code.is_active = False
            code.save(update_fields=['is_active'])
        else:
            seen.add(key)

    Service.objects.exclude(code__in=CANONICAL).update(is_active=False)


def reverse_organize_catalog(apps, schema_editor):
    # Data consolidation is intentionally irreversible: restoring duplicate
    # service rows could detach historical USSD and transaction records.
    pass


class Migration(migrations.Migration):
    dependencies = [('core', '0024_canonical_services')]
    operations = [migrations.RunPython(organize_catalog, reverse_organize_catalog)]
