#!/usr/bin/env python3
"""
Script utilitaire autonome pour administrer les Gateways USSD :
- Créer une nouvelle Gateway et générer sa clé secrète (X-Gateway-Secret)
- Régénérer la clé d'une Gateway existante (--reset)
- Lister toutes les Gateways enregistrées (--list)
- Supprimer une Gateway ou toutes les Gateways résiduelles (--delete / --delete-all)

Utilisation :
  python scripts/create_gateway.py --name "Orange Gateway 01"
  python scripts/create_gateway.py --name "Orange Gateway 01" --reset
  python scripts/create_gateway.py --list
  python scripts/create_gateway.py --delete "Serveur USSD 1"
  python scripts/create_gateway.py --delete-all

Dans un environnement Docker en production :
  docker compose exec backend python scripts/create_gateway.py --name "Orange Gateway 01"
  docker compose exec backend python scripts/create_gateway.py --delete-all
"""

import os
import sys
import argparse

# Configuration automatique de l'environnement Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'transfer_on_line.settings')

import django
django.setup()

from apps.core.models import Gateway, TransactionAttempt
from apps.devices.services.gateway_manager import IN_FLIGHT_STATUSES


def list_gateways():
    gateways = list(Gateway.objects.all().order_by('id'))
    print("=" * 70)
    print(f"📋 GATEWAYS ENREGISTRÉES DANS LA BASE ({len(gateways)}) :")
    print("=" * 70)
    if not gateways:
        print("  Aucune Gateway trouvée en base de données.")
        print("=" * 70)
        return

    for gw in gateways:
        secret_status = "Configuré (SHA-256)" if gw.api_key_hash else "NON CONFIGURÉ"
        active_status = "Active" if gw.is_active else "Inactive"
        print(f"  [ID: {gw.id}] Nom: '{gw.name}' | Statut: {gw.status} | {active_status} | Clé: {secret_status}")
    print("=" * 70)


def delete_gateway(identifier):
    if identifier.isdigit():
        gw = Gateway.objects.filter(id=int(identifier)).first()
    else:
        gw = Gateway.objects.filter(name=identifier).first()

    if not gw:
        print(f"❌ Aucune Gateway trouvée avec l'identifiant ou nom '{identifier}'.")
        return

    # Vérification des transactions en vol
    in_flight = TransactionAttempt.objects.filter(
        gateway_sim__gateway=gw, status__in=IN_FLIGHT_STATUSES
    ).exists()
    if in_flight:
        print(f"❌ Impossible de supprimer la Gateway '{gw.name}' (ID: {gw.id}) : des transactions sont en cours.")
        return

    name = gw.name
    gw_id = gw.id
    gw.delete()
    print(f"✅ Gateway '{name}' (ID: {gw_id}) supprimée avec succès.")


def delete_all_gateways():
    in_flight = TransactionAttempt.objects.filter(
        status__in=IN_FLIGHT_STATUSES
    ).exists()
    if in_flight:
        print("❌ Impossible de supprimer les gateways : des transactions sont actuellement en cours d'exécution.")
        return

    count, _ = Gateway.objects.all().delete()
    print(f"✅ Toutes les Gateways résiduelles ont été supprimées de la base ({count} enregistrements supprimés).")


def create_or_reset_gateway(name, reset=False):
    name = name.strip()
    if not name:
        print("❌ Le nom de la Gateway ne peut pas être vide.")
        return

    gateway, created = Gateway.objects.get_or_create(
        name=name,
        defaults={'is_active': True, 'status': 'offline'},
    )

    if not created and not reset and gateway.api_key_hash:
        print("=" * 70)
        print(f"⚠️  La Gateway '{name}' (ID: {gateway.id}) existe déjà avec une clé configurée.")
        print("   Pour régénérer une nouvelle clé pour cette gateway :")
        print(f"   python scripts/create_gateway.py --name \"{name}\" --reset")
        print("=" * 70)
        return

    secret = gateway.generate_secret()
    gateway.is_active = True
    gateway.save(update_fields=['is_active'])

    print("=" * 70)
    print("✅ GATEWAY CRÉÉE / RÉINITIALISÉE AVEC SUCCÈS")
    print("=" * 70)
    print(f"  ID Gateway       : {gateway.id}")
    print(f"  Nom Gateway      : {gateway.name}")
    print(f"  Statut           : {'Actif (en attente de connexion)' if gateway.is_active else 'Inactif'}")
    print("-" * 70)
    print("  CLÉ SECRÈTE (X-Gateway-Secret) :")
    print("  ⚠️  ATTENTION : Cette clé n'est affichée qu'UNE SEULE FOIS.")
    print("  (En base, seul le hash cryptographique SHA-256 est conservé)")
    print(f"\n      {secret}\n")
    print("-" * 70)
    print("  Configuration sur le téléphone Android (Application Gateway) :")
    print("  1. Ouvrez l'application Transfer On Line Gateway.")
    print("  2. Dans l'écran de configuration :")
    print("     - URL du Serveur : https://<votre-domaine>/api")
    print(f"     - Gateway Secret : {secret}")
    print("  3. Cliquez sur 'Tester la connexion' puis 'Enregistrer'.")
    print("  4. Démarrez le service d'arrière-plan.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Gestion et provisionnement des Gateways USSD.")
    parser.add_argument('--name', type=str, help="Nom de la Gateway à créer ou réinitialiser.")
    parser.add_argument('--reset', action='store_true', help="Force la régénération d'une nouvelle clé secrète.")
    parser.add_argument('--list', action='store_true', help="Lister toutes les gateways enregistrées.")
    parser.add_argument('--delete', type=str, help="Supprimer une gateway par son ID ou son nom.")
    parser.add_argument('--delete-all', action='store_true', help="Supprimer toutes les gateways résiduelles.")

    args = parser.parse_args()

    if args.list:
        list_gateways()
    elif args.delete:
        delete_gateway(args.delete)
    elif args.delete_all:
        delete_all_gateways()
    elif args.name:
        create_or_reset_gateway(args.name, reset=args.reset)
    else:
        # Si aucun argument n'est passé, lister les gateways actuelles et afficher l'aide
        list_gateways()
        print("\n💡 Astuce :")
        print("  Pour créer une Gateway : python scripts/create_gateway.py --name \"Mon Serveur\"")
        print("  Pour régénérer la clé  : python scripts/create_gateway.py --name \"Mon Serveur\" --reset")
        print("  Pour supprimer         : python scripts/create_gateway.py --delete \"Nom ou ID\"")


if __name__ == '__main__':
    main()
