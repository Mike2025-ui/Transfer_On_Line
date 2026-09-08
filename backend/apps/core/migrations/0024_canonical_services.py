from django.db import migrations


def canonicalize_services(apps, schema_editor):
    Service = apps.get_model('core', 'Service')
    canonical = {
        'voix': 'Appels (Pass voix)',
        'internet': 'Internet (Pass data)',
        'credit': 'Crédit (communication)',
        'sms': 'SMS (Pass SMS)',
    }
    aliases = {'apple': 'voix', 'transfert_unite': 'credit', 'subscription': 'internet'}

    for old_code, new_code in aliases.items():
        source = Service.objects.filter(code=old_code).first()
        target = Service.objects.filter(code=new_code).first()
        if source and not target:
            source.code = new_code
            source.name = canonical[new_code]
            source.is_active = True
            source.save(update_fields=['code', 'name', 'is_active'])

    for code, name in canonical.items():
        service, _ = Service.objects.get_or_create(code=code, defaults={'name': name})
        if service.name != name or not service.is_active:
            service.name = name
            service.is_active = True
            service.save(update_fields=['name', 'is_active'])

    Service.objects.exclude(code__in=canonical).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [('core', '0023_create_services')]
    operations = [migrations.RunPython(canonicalize_services, migrations.RunPython.noop)]