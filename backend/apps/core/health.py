import logging

import requests
from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)


def check_database():
    """Runs on its own thread (see apps.core.views._run_concurrently), so the
    connection it lazily opens is explicitly closed afterwards - otherwise a
    health check hit every few seconds by a probe would slowly leak idle
    per-thread DB connections that Django's normal request-cycle cleanup
    never sees."""
    try:
        connections['default'].ensure_connection()
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
        return 'ok'
    except OperationalError as exc:
        logger.error('Health check: database unreachable: %s', exc)
        return 'down'
    finally:
        connections['default'].close()


def check_redis():
    try:
        import redis
        from redis.backoff import NoBackoff
        from redis.retry import Retry
    except ImportError:  # pragma: no cover - redis client always ships with this project
        return 'not_configured'
    try:
        # redis-py retries a failed connection once by default regardless of
        # socket_connect_timeout, silently doubling the real worst-case wait -
        # Retry(NoBackoff(), 0) turns that off so this check stays bounded.
        client = redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1, retry=Retry(NoBackoff(), 0),
        )
        client.ping()
        return 'ok'
    except redis.exceptions.RedisError as exc:
        logger.warning('Health check: redis unreachable: %s', exc)
        return 'down'


def check_provider_reachable(base_url, *, connect_timeout=1, read_timeout=1):
    """'ok' only means the provider's API answered something (even an
    error/auth-rejected response) within the timeout - it does NOT validate
    our credentials. A payment provider being unreachable is reported here
    for visibility but never flips readiness to false: our own service can
    keep serving everything else (dashboard, gateway heartbeats, USSD
    reporting) while a provider is down. Timeouts are intentionally tight -
    a health check must stay fast regardless of a slow/dead upstream, or it
    risks failing the load balancer's own probe timeout."""
    if not base_url:
        return 'not_configured'
    try:
        requests.head(base_url, timeout=(connect_timeout, read_timeout))
        return 'ok'
    except requests.exceptions.RequestException as exc:
        logger.warning('Health check: %s unreachable: %s', base_url, exc)
        return 'down'


def gateway_summary():
    """Also runs on its own thread - see check_database's docstring on why
    the connection is closed explicitly at the end."""
    from apps.core.models import Gateway
    try:
        return {
            'status': 'ok',
            'online_count': Gateway.objects.filter(status='online').count(),
            'total_count': Gateway.objects.count(),
        }
    finally:
        connections['default'].close()
