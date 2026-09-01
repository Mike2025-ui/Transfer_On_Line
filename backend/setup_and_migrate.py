#!/usr/bin/env python
"""
Script complet pour:
1. Supprimer la migration en doublon
2. Appliquer les migrations
3. Créer les services
"""
import os
import sys
import subprocess
import django

# Chemin backend
backend_path = r'c:\Users\TOSHIBA\Desktop\Transfer_On_Line\backend'
os.chdir(backend_path)
sys.path.insert(0, backend_path)

# 1. Supprimer l'ancienne migration en doublon
print("=" * 60)
print("ÉTAPE 1: Supprimer la migration en doublon")
print("=" * 60)
old_migration = os.path.join(backend_path, 'apps', 'core', 'migrations', '0014_create_services.py')
if os.path.exists(old_migration):
    os.remove(old_migration)
    print(f"✅ Supprimé: 0014_create_services.py")
else:
    print(f"ℹ️  Fichier introuvable (déjà supprimé?)")

# 2. Appliquer les migrations
print("\n" + "=" * 60)
print("ÉTAPE 2: Appliquer les migrations")
print("=" * 60)
try:
    result = subprocess.run(
        ['python', 'manage.py', 'migrate'],
        capture_output=True,
        text=True,
        timeout=30
    )
    if result.returncode == 0:
        print("✅ Migrations appliquées avec succès")
        if result.stdout:
            print("Output:")
            print(result.stdout[-500:])  # Dernières 500 chars
    else:
        print(f"❌ Erreur lors des migrations")
        print("stderr:", result.stderr[-500:] if result.stderr else "N/A")
except Exception as e:
    print(f"❌ Erreur: {e}")
    sys.exit(1)

# 3. Créer les services
print("\n" + "=" * 60)
print("ÉTAPE 3: Créer les services")
print("=" * 60)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'transfer_on_line.settings')
django.setup()

from apps.core.models import Service

services_data = [
    {'name': 'Souscription Appelle', 'code': 'apple'},
    {'name': 'Souscription SMS', 'code': 'sms'},
    {'name': 'Souscription Internet', 'code': 'internet'},
    {'name': 'Transfert d\'unité', 'code': 'transfert_unite'},
]

print("\nMise à jour des services...")
for service_data in services_data:
    service, created = Service.objects.update_or_create(
        code=service_data['code'],
        defaults={'name': service_data['name'], 'is_active': True}
    )
    status = "créé" if created else "mis à jour"
    print(f"  ✅ {service_data['name']} ({status})")

print("\nServices en base de données:")
services = Service.objects.all().order_by('name')
for s in services:
    print(f"  - {s.name} (code={s.code}, is_active={s.is_active})")

print(f"\n✅ DONE: {services.count()} services en total")
print("=" * 60)
