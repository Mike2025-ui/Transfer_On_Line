from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.health import check_database, check_provider_reachable, check_redis, gateway_summary


def _run_concurrently(named_checks):
    """Runs independent, blocking I/O checks (HTTP/DB/Redis) in parallel so
    the endpoint's total latency is the slowest single check, not their sum -
    a health check must not become slower than the sum of every dependency
    it inspects."""
    with ThreadPoolExecutor(max_workers=len(named_checks)) as pool:
        futures = {name: pool.submit(func) for name, func in named_checks.items()}
        return {name: future.result() for name, future in futures.items()}


class LivenessView(APIView):
    """Is the process alive at all? No DB/network calls, on purpose: a
    Kubernetes/Docker liveness probe restarts the container when this fails,
    and restarting a process cannot fix a database or Redis outage - only
    readiness should react to those."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'status': 'ok'})


class ReadinessView(APIView):
    """Can this instance actually serve traffic right now? Gates on the
    database (nothing works without it). Redis is reported for visibility
    but does not fail readiness on its own: it currently only backs RQ,
    which nothing in this codebase enqueues to yet (see apps/payments -
    reconciliation runs as a management command, not a queued job)."""

    permission_classes = [AllowAny]

    def get(self, request):
        checks = _run_concurrently({'database': check_database, 'redis': check_redis})
        ready = checks['database'] == 'ok'
        return Response({'status': 'ok' if ready else 'unavailable', **checks}, status=200 if ready else 503)


class HealthCheckView(APIView):
    """Deep, human/dashboard-facing health check. Payment provider
    reachability is informational only - see check_provider_reachable's
    docstring for why it must never gate overall status."""

    permission_classes = [AllowAny]

    def get(self, request):
        checks = _run_concurrently({
            'database': check_database,
            'redis': check_redis,
            'geniuspay': lambda: check_provider_reachable(settings.GENIUSPAY_BASE_URL),
            'cinetpay': lambda: check_provider_reachable(settings.CINETPAY_INIT_URL),
            'gateway': gateway_summary,
        })
        overall = 'ok' if checks['database'] == 'ok' else 'degraded'
        return Response({'status': overall, **checks}, status=200 if overall == 'ok' else 503)
