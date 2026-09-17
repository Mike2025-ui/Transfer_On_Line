from django.core.management.base import BaseCommand
from apps.core.models import Gateway


class Command(BaseCommand):
    help = (
        'Provisionne ou réinitialise une Gateway (téléphone serveur USSD) '
        'et génère son X-Gateway-Secret cryptographique.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            default='Serveur USSD 1',
            help='Nom de la Gateway (défaut : "Serveur USSD 1")',
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Force la régénération d’un nouveau secret si la Gateway existe déjà.',
        )

    def handle(self, *args, **options):
        name = options['name'].strip()
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

