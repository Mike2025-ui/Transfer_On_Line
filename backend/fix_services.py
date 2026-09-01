import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'transfer_on_line.settings')
sys.path.insert(0, os.path.dirname(__file__))

import django
django.setup()

from apps.core.models import Service

TARGETS = [
    {'code': 'apple', 'name': 'Souscription Appelle'},
    {'code': 'sms', 'name': 'Souscription SMS'},
    {'code': 'internet', 'name': 'Souscription Internet'},
    {'code': 'transfert_unite', 'name': "Transfert d'unité"},
]

print('Services avant nettoyage:')
for s in Service.objects.order_by('name'):
    print(f' - {s.id}: {s.name} | code={s.code} | active={s.is_active}')

# Remove legacy generic duplicates that were created with code='subscription'
legacy_codes_to_remove = {'subscription'}
legacy_rows = Service.objects.filter(code__in=legacy_codes_to_remove)
if legacy_rows.exists():
    print('\nSuppression des services legacy avec code subscription...')
    legacy_rows.delete()

# Keep exactly the 4 required services, merge duplicates, ensure active state
for target in TARGETS:
    rows = list(Service.objects.filter(code=target['code']).order_by('id'))
    if not rows:
        Service.objects.create(name=target['name'], code=target['code'], is_active=True)
        print(f"Création: {target['name']} ({target['code']})")
        continue

    keep = rows[0]
    keep.name = target['name']
    keep.is_active = True
    keep.save(update_fields=['name', 'is_active'])
    for extra in rows[1:]:
        print(f"Suppression du doublon: {extra.name} ({extra.code})")
        extra.delete()

# Cleanup any stray duplicates or wrong names by code
for target in TARGETS:
    rows = list(Service.objects.filter(code=target['code']).order_by('id'))
    if rows:
        main = rows[0]
        main.name = target['name']
        main.is_active = True
        main.save(update_fields=['name', 'is_active'])
        for extra in rows[1:]:
            extra.delete()

print('\nServices après nettoyage:')
for s in Service.objects.order_by('name'):
    print(f' - {s.id}: {s.name} | code={s.code} | active={s.is_active}')

print(f'\nTotal final: {Service.objects.count()} services')
