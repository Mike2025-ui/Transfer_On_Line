import logging
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.db.models import Q

from apps.core.models import Operator, Transaction, UssdCode
from apps.devices.models import GatewaySim
from apps.core.services.retry_manager import RetryManager

logger = logging.getLogger(__name__)

CANONICAL_OPERATORS = [
    {'name': 'MTN', 'code': 'mtn'},
    {'name': 'Orange', 'code': 'orange'},
    {'name': 'Moov', 'code': 'moov'},
    {'name': 'Wave', 'code': 'wave'},
]


class Command(BaseCommand):
    help = (
        'Nettoie et fusionne les opérateurs en doublon créés par la télémétrie SIM (ex: "Mtn" vs "MTN"), '
        'réaffecte les cartes SIM, transactions et codes USSD à l\'opérateur canonique, '
        'et relance le dispatch des transactions en attente.'
    )

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("NETTOYAGE ET HARMONISATION DES OPÉRATEURS")
        self.stdout.write("=" * 60)

        with db_transaction.atomic():
            for target in CANONICAL_OPERATORS:
                code = target['code']
                name = target['name']

                # Trouver l'opérateur canonique existant ou le premier correspondant
                canonical = (
                    Operator.objects.filter(code=code).order_by('id').first()
                    or Operator.objects.filter(name__iexact=name).order_by('id').first()
                )

                if not canonical:
                    canonical = Operator.objects.create(name=name, code=code, is_active=True)
                    self.stdout.write(self.style.SUCCESS(f"Opérateur canonique créé: {canonical.name} (id={canonical.id})"))
                else:
                    # S'assurer que le nom et le code sont propres
                    if canonical.name != name or canonical.code != code:
                        canonical.name = name
                        canonical.code = code
                        canonical.save(update_fields=['name', 'code'])
                    self.stdout.write(f"Opérateur canonique: {canonical.name} (id={canonical.id}, code={canonical.code})")

                # Trouver tous les doublons (même préfixe ou code insensible à la casse, mais id différent)
                duplicates = Operator.objects.filter(
                    Q(code__iexact=code) | Q(name__icontains=code) | Q(name__icontains=name)
                ).exclude(id=canonical.id)

                for dup in duplicates:
                    self.stdout.write(self.style.WARNING(
                        f"  -> Fusion du doublon: '{dup.name}' (id={dup.id}, code='{dup.code}') vers '{canonical.name}' (id={canonical.id})"
                    ))

                    # Réaffecter les transactions
                    tx_count = Transaction.objects.filter(operator=dup).update(operator=canonical)
                    if tx_count:
                        self.stdout.write(f"     {tx_count} transaction(s) réaffectée(s)")

                    # Réaffecter les cartes SIM
                    sim_count = GatewaySim.objects.filter(operator=dup).update(operator=canonical)
                    if sim_count:
                        self.stdout.write(f"     {sim_count} carte(s) SIM réaffectée(s)")

                    # Réaffecter les codes USSD
                    ussd_count = UssdCode.objects.filter(operator=dup).update(operator=canonical)
                    if ussd_count:
                        self.stdout.write(f"     {ussd_count} code(s) USSD réaffecté(s)")

                    dup.delete()
                    self.stdout.write(self.style.SUCCESS(f"     Doublon id={dup.id} supprimé."))

        # S'assurer que les Gateways ont au moins une SIM active sur leur opérateur détecté
        from apps.core.models import Gateway
        for gw in Gateway.objects.filter(is_active=True):
            if not gw.sims.exists():
                op_name = (gw.name.split('-')[0] if '-' in gw.name else '').strip()
                op = Operator.objects.filter(name__icontains=op_name).first() or Operator.objects.filter(code='mtn').first()
                if op:
                    GatewaySim.objects.create(gateway=gw, slot=0, operator=op, is_active=True)
                    self.stdout.write(self.style.SUCCESS(
                        f"SIM par défaut créée pour Gateway '{gw.name}': slot 0, opérateur={op.name}"
                    ))

        self.stdout.write("=" * 60)
        self.stdout.write("RELANCE DU DISPATCH DES TRANSACTIONS EN ATTENTE...")
        results = RetryManager.dispatch_due_retries()
        dispatched = sum(1 for attempt in results.values() if attempt is not None)
        self.stdout.write(self.style.SUCCESS(
            f"Dispatch terminé : {len(results)} traitée(s), {dispatched} assignée(s) à un Gateway."
        ))
        self.stdout.write("=" * 60)
