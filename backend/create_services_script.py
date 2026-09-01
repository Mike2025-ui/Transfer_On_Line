#!/usr/bin/env python
import os
import sys
import django

os.chdir(r'c:\Users\TOSHIBA\Desktop\Transfer_On_Line\backend')
sys.path.insert(0, r'c:\Users\TOSHIBA\Desktop\Transfer_On_Line\backend')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'transfer_on_line.settings')
django.setup()

from apps.core.models import Service

# Create services
services_to_create = [
    {'name': 'Souscription Appelle', 'code': 'apple'},
    {'name': 'Souscription SMS', 'code': 'sms'},
    {'name': 'Souscription Internet', 'code': 'internet'},
    {'name': 'Transfert d\'unité', 'code': 'transfert_unite'},
]

print("\nCreating services...")
for service_data in services_to_create:
    service, created = Service.objects.update_or_create(
        code=service_data['code'],
        defaults={'name': service_data['name'], 'is_active': True}
    )
    status = "created" if created else "updated"
    print(f"  ✅ {service_data['name']} ({status})")

print("\nServices in database:")
for s in Service.objects.all().order_by('name'):
    print(f"  - {s.name} (code={s.code}, is_active={s.is_active})")

print(f"\nTotal: {Service.objects.count()} services")
