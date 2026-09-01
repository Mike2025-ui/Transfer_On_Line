# Generated migration to create and update services

from django.db import migrations
from django.db.models import Q

def create_services(apps, schema_editor):
    Service = apps.get_model('core', 'Service')
    
    services_data = [
        {'name': 'Souscription Appelle', 'code': 'apple'},
        {'name': 'Souscription SMS', 'code': 'sms'},
        {'name': 'Souscription Internet', 'code': 'internet'},
        {'name': 'Transfert d\'unité', 'code': 'transfert_unite'},
    ]
    
    for service_data in services_data:
        Service.objects.update_or_create(
            code=service_data['code'],
            defaults={'name': service_data['name'], 'is_active': True}
        )

def reverse_services(apps, schema_editor):
    Service = apps.get_model('core', 'Service')
    Service.objects.filter(code__in=['apple', 'sms', 'internet', 'transfert_unite']).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_remove_cinetpay_feexpay'),
    ]

    operations = [
        migrations.RunPython(create_services, reverse_services),
    ]
