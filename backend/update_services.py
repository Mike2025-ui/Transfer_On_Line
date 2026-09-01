#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'transfer_on_line.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from apps.core.models import Service

# Services à créer/mettre à jour
services_data = [
    {'name': 'Souscription Appelle', 'code': 'apple'},
    {'name': 'Souscription SMS', 'code': 'sms'},
    {'name': 'Souscription Internet', 'code': 'internet'},
    {'name': 'Transfert d\'unité', 'code': 'transfert_unite'},
]

print("=" * 60)
print("Mise à jour des services")
print("=" * 60)

for service_data in services_data:
    service, created = Service.objects.update_or_create(
        code=service_data['code'],
        defaults={'name': service_data['name'], 'is_active': True}
    )
    status = "✅ créé" if created else "✅ mis à jour"
    print(f"{status}: {service.name} (code={service.code})")

print("\n" + "=" * 60)
print("Services disponibles après mise à jour:")
print("=" * 60)
for s in Service.objects.all().order_by('name'):
    status = "✅ Actif" if s.is_active else "⚠️  Inactif"
    print(f"{s.name:30} | code={s.code:20} | {status}")
print("=" * 60)
