import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import Gateway

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Marks Android gateways offline if they have not sent a heartbeat '
        'recently. GatewayHeartbeatView only ever sets a gateway online - '
        'nothing currently notices when a phone goes silent (killed app, dead '
        'battery, lost connectivity). Safe to run repeatedly via cron.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--stale-after-minutes', type=int, default=5,
            help='Mark a gateway offline if its last heartbeat is older than this (default: 5).',
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options['stale_after_minutes'])
        stale = Gateway.objects.filter(status='online').filter(
            last_heartbeat__lt=cutoff,
        ) | Gateway.objects.filter(status='online', last_heartbeat__isnull=True)

        count = stale.update(status='offline')
        if count:
            logger.warning('Marked %s gateway(s) offline (no heartbeat since %s)', count, cutoff.isoformat())
        self.stdout.write(self.style.SUCCESS(f'{count} gateway(s) marked offline.'))
