from django.core.management.base import BaseCommand
from apps.core.models import Gateway, TransactionAttempt
from apps.devices.services.gateway_manager import IN_FLIGHT_STATUSES


class Command(BaseCommand):
    help = (
        'Provisionne, liste ou supprime des Gateways (téléphones serveurs USSD) '
        'et gère leur X-Gateway-Secret cryptographique.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            default=None,
            help='Nom de la Gateway (défaut si création sans option : "Serveur USSD 1")',
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Force la régénération d’un nouveau secret si la Gateway existe déjà.',
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='Liste toutes les Gateways enregistrées en base.',
        )
        parser.add_argument(
            '--delete',
            type=str,
            help='Supprime une Gateway par son ID ou son nom.',
        )
        parser.add_argument(
            '--delete-all',
            action='store_true',
            help='Supprime toutes les Gateways résiduelles.',
        )

    def handle(self, *args, **options):
        if options['list']:
            return self._list_gateways()

        if options['delete']:
            return self._delete_gateway(options['delete'])

        if options['delete_all']:
            return self._delete_all_gateways()

        name = (options['name'] or 'Serveur USSD 1').strip()
        reset = options['reset']

        gateway, created = Gateway.objects.get_or_create(
            name=name,
            defaults={'is_active': True, 'status': 'offline'},
        )

        if not created and not reset and gateway.api_key_hash:
            self.stdout.write(self.style.WARNING(
                f"La Gateway '{name}' (ID: {gateway.id}) existe déjà avec un secret configuré.\n"
                f"Pour régénérer son secret, utilisez : python manage.py setup_gateway --name \"{name}\" --reset"
            ))
            return

        secret = gateway.generate_secret()
        gateway.is_active = True
        gateway.save(update_fields=['is_active'])

        self.stdout.write("=" * 60)
        self.stdout.write(self.style.SUCCESS("✅ CONFIGURATION GATEWAY SERVEUR USSD TERMINÉE"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"ID Gateway   : {gateway.id}")
        self.stdout.write(f"Nom Gateway  : {gateway.name}")
        self.stdout.write(f"Statut       : {'Actif (en attente de connexion)' if gateway.is_active else 'Inactif'}")
        self.stdout.write("-" * 60)
        self.stdout.write(self.style.WARNING("SECRET GATEWAY (affiché UNE SEULE FOIS, à copier sur le téléphone) :"))
        self.stdout.write(self.style.SUCCESS(f"\n  {secret}\n"))
        self.stdout.write("-" * 60)
        self.stdout.write("Instructions pour le téléphone serveur USSD :")
        self.stdout.write("1. Ouvrez l'application Gateway sur le téléphone Android.")
        self.stdout.write("2. Dans la configuration (ou lors de la première ouverture) :")
        self.stdout.write("   - URL API        : https://transfert-online.site/api")
        self.stdout.write(f"   - Gateway Secret : {secret}")
        self.stdout.write("3. Cliquez sur 'ENREGISTRER' puis 'TESTER LA CONNEXION'.")
        self.stdout.write("4. Démarrez le service d'arrière-plan pour traiter les USSD.")
        self.stdout.write("=" * 60)

    def _list_gateways(self):
        gateways = list(Gateway.objects.all().order_by('id'))
        self.stdout.write("=" * 70)
        self.stdout.write(f"📋 GATEWAYS ENREGISTRÉES DANS LA BASE ({len(gateways)}) :")
        self.stdout.write("=" * 70)
        if not gateways:
            self.stdout.write("  Aucune Gateway trouvée en base de données.")
            self.stdout.write("=" * 70)
            return

        for gw in gateways:
            secret_status = "Configuré (SHA-256)" if gw.api_key_hash else "NON CONFIGURÉ"
            active_status = "Active" if gw.is_active else "Inactive"
            self.stdout.write(f"  [ID: {gw.id}] Nom: '{gw.name}' | Statut: {gw.status} | {active_status} | Clé: {secret_status}")
        self.stdout.write("=" * 70)

    def _delete_gateway(self, identifier):
        if identifier.isdigit():
            gw = Gateway.objects.filter(id=int(identifier)).first()
        else:
            gw = Gateway.objects.filter(name=identifier).first()

        if not gw:
            self.stdout.write(self.style.ERROR(f"❌ Aucune Gateway trouvée avec l'identifiant ou nom '{identifier}'."))
            return

        in_flight = TransactionAttempt.objects.filter(
            gateway_sim__gateway=gw, status__in=IN_FLIGHT_STATUSES
        ).exists()
        if in_flight:
            self.stdout.write(self.style.ERROR(f"❌ Impossible de supprimer la Gateway '{gw.name}' (ID: {gw.id}) : des transactions sont en cours."))
            return

        name = gw.name
        gw_id = gw.id
        gw.delete()
        self.stdout.write(self.style.SUCCESS(f"✅ Gateway '{name}' (ID: {gw_id}) supprimée avec succès."))

    def _delete_all_gateways(self):
        in_flight = TransactionAttempt.objects.filter(
            status__in=IN_FLIGHT_STATUSES
        ).exists()
        if in_flight:
            self.stdout.write(self.style.ERROR("❌ Impossible de supprimer les gateways : des transactions sont actuellement en cours d'exécution."))
            return

        count, _ = Gateway.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"✅ Toutes les Gateways résiduelles ont été supprimées de la base ({count} enregistrements supprimés)."))
