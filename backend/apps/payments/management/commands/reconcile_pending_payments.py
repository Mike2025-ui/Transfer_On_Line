from django.core.management.base import BaseCommand

from apps.payments.services.payment_service import PaymentService


class Command(BaseCommand):
    help = (
        'Actively re-verify payments stuck in "pending" against their provider, '
        'and mark abandoned ones as failed once past their checkout expiry. '
        'Safe to run repeatedly (e.g. every few minutes via cron) - all writes '
        'go through the same idempotent PaymentService.apply_status() used by webhooks.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--stale-after-minutes', type=int, default=10,
            help='Only touch payments that have been pending for at least this long (default: 10).',
        )
        parser.add_argument(
            '--expire-after-hours', type=int, default=24,
            help='Payments older than this are marked failed without calling the provider (default: 24, matches GeniusPay checkout link expiry).',
        )

    def handle(self, *args, **options):
        result = PaymentService.reconcile_pending(
            stale_after_minutes=options['stale_after_minutes'],
            expire_after_hours=options['expire_after_hours'],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Checked {result['checked']} pending payment(s): "
            f"{result['verified']} re-verified, {result['expired']} expired, {result['errors']} error(s)."
        ))
