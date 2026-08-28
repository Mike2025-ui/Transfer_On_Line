import logging

from django.core.management.base import BaseCommand

from apps.core.services.retry_manager import RetryManager
from apps.devices.services.reservation_manager import ReservationManager

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Phase D audit (Critique - retry dispatch never wired to a scheduler): '
        'releases expired in-flight reservations, then dispatches every '
        'Transaction whose next_retry_at has elapsed to a freshly selected '
        'GatewaySim. RetryManager.dispatch_due_retries() and '
        'ReservationManager.release_expired() already existed and were fully '
        'tested, but had no caller anywhere outside tests - with '
        'USE_NEW_TRANSACTION_ENGINE enabled, a retry-eligible failure would '
        'silently strand its transaction in "pending" forever without this. '
        'Safe to run repeatedly (e.g. every minute via cron), same family as '
        'check_gateway_health/reconcile_pending_payments.'
    )

    def handle(self, *args, **options):
        released = ReservationManager.release_expired()
        if released:
            self.stdout.write(f'{released} expired reservation(s) released.')

        results = RetryManager.dispatch_due_retries()
        dispatched = sum(1 for attempt in results.values() if attempt is not None)
        no_gateway = len(results) - dispatched
        if no_gateway:
            logger.warning('%s due retry(ies) had no eligible GatewaySim available', no_gateway)

        self.stdout.write(self.style.SUCCESS(
            f'{len(results)} due retry(ies) processed: {dispatched} dispatched, {no_gateway} with no gateway available.'
        ))
