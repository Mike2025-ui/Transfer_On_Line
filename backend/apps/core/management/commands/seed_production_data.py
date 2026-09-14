from decimal import Decimal
from django.core.management.base import BaseCommand
from apps.core.models import Operator, Service, UssdCode


class Command(BaseCommand):
    help = 'Seeds canonical operators, services, and default USSD codes into the production database.'

    def handle(self, *args, **options):
        self.stdout.write("--- Seeding Operators ---")
        operators_info = [
            {'name': 'Orange', 'code': 'orange', 'is_active': True},
            {'name': 'MTN', 'code': 'mtn', 'is_active': True},
            {'name': 'Moov', 'code': 'Moov', 'is_active': True},
        ]
        created_ops = {}
        for op in operators_info:
            obj, created = Operator.objects.update_or_create(
                name=op['name'],
                defaults={'code': op['code'], 'is_active': op['is_active']},
            )
            created_ops[op['name']] = obj
            status = 'Created' if created else 'Updated/Exists'
            self.stdout.write(f"  [{status}] Operator: {obj.name} (id={obj.id}, code={obj.code})")

        self.stdout.write("\n--- Seeding Services ---")
        services_info = [
            {'name': 'Appels (Pass voix)', 'code': 'voix', 'is_active': True},
            {'name': 'Internet (Pass data)', 'code': 'internet', 'is_active': True},
            {'name': 'Crédit (communication)', 'code': 'credit', 'is_active': True},
            {'name': 'SMS (Pass SMS)', 'code': 'sms', 'is_active': True},
        ]
        created_svcs = {}
        for svc in services_info:
            obj, created = Service.objects.update_or_create(
                name=svc['name'],
                defaults={'code': svc['code'], 'is_active': svc['is_active']},
            )
            created_svcs[svc['code']] = obj
            status = 'Created' if created else 'Updated/Exists'
            self.stdout.write(f"  [{status}] Service: {obj.name} (id={obj.id}, code={obj.code})")

        self.stdout.write("\n--- Seeding USSD Codes ---")
        # Base fallback templates for each operator
        for op_name, op in created_ops.items():
            # 1. Operator-level fallback (service=None)
            fallback, f_created = UssdCode.objects.get_or_create(
                operator=op,
                service=None,
                amount=None,
                defaults={
                    'label': 'Autre / Général',
                    'template': '*456*{montant}#',
                    'is_active': True,
                    'is_default': True,
                },
            )
            self.stdout.write(f"  Operator fallback: {op.name} -> {fallback.template}")

            # 2. Service-level templates
            for s_code, svc in created_svcs.items():
                is_credit = s_code == 'credit'
                template = '*123*{numero}*{montant}#' if is_credit else '*456*{montant}#'
                label = 'Transfert d\'unité' if is_credit else f'Pass {svc.name}'
                code_obj, c_created = UssdCode.objects.get_or_create(
                    operator=op,
                    service=svc,
                    amount=None,
                    defaults={
                        'label': label,
                        'template': template,
                        'is_active': True,
                        'is_default': False,
                    },
                )

        # 3. Dedicated amount configurations for testing / bundles
        mtn_op = created_ops.get('MTN')
        if mtn_op:
            credit_svc = created_svcs.get('credit')
            voix_svc = created_svcs.get('voix')
            internet_svc = created_svcs.get('internet')

            if credit_svc:
                UssdCode.objects.get_or_create(
                    operator=mtn_op,
                    service=credit_svc,
                    amount=Decimal('500'),
                    defaults={
                        'label': 'transfert unité 500',
                        'template': '*133*5*{numero}*{montant}',
                        'is_active': True,
                        'is_default': False,
                    },
                )
            if voix_svc:
                UssdCode.objects.get_or_create(
                    operator=mtn_op,
                    service=voix_svc,
                    amount=Decimal('500'),
                    defaults={
                        'label': 'Souscription Appelle 500',
                        'template': '*133*6*2*{numero}#',
                        'is_active': True,
                        'is_default': False,
                    },
                )
            if internet_svc:
                UssdCode.objects.get_or_create(
                    operator=mtn_op,
                    service=internet_svc,
                    amount=Decimal('500'),
                    defaults={
                        'label': 'Souscription internet 500',
                        'template': '*133*6*2*{numero}#',
                        'is_active': True,
                        'is_default': False,
                    },
                )

        self.stdout.write(self.style.SUCCESS("\n✅ All production seed data initialized successfully!"))

