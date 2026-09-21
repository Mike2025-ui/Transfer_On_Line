from django.core.management.base import BaseCommand
from apps.core.models import Operator


class Command(BaseCommand):
    help = 'Seeds canonical operators (Orange, MTN, Moov) into the database.'

    def handle(self, *args, **options):
        self.stdout.write("--- Seeding Operators Only ---")
        operators_info = [
            {'name': 'Orange', 'code': 'orange', 'is_active': True},
            {'name': 'MTN', 'code': 'mtn', 'is_active': True},
            {'name': 'Moov', 'code': 'Moov', 'is_active': True},
        ]
        for op in operators_info:
            obj, created = Operator.objects.update_or_create(
                name=op['name'],
                defaults={'code': op['code'], 'is_active': op['is_active']},
            )
            status = 'Created' if created else 'Updated/Exists'
            self.stdout.write(f"  [{status}] Operator: {obj.name} (id={obj.id}, code={obj.code})")

        self.stdout.write(self.style.SUCCESS("\n✅ Operators initialized successfully! No services or USSD codes seeded."))

