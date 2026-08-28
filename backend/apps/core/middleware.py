import logging
import time

from django.conf import settings

from apps.core.correlation import HEADER_NAME, get_correlation_id, new_id, set_correlation_id

logger = logging.getLogger('apps.core.request_timing')


class CorrelationIdMiddleware:
    """Assigns a correlation id to every request: reuses the caller's
    X-Correlation-ID header if it sent one, otherwise generates a fresh one.
    Echoed back in the response header so Flutter/the Android Gateway can log
    it too. Views that operate on a specific Transaction (ExecuteTransactionView,
    the payment webhooks, TransactionResultView) overwrite it with
    Transaction.reference - the id already shown to the end user and to the
    gateway - so "one id to find everything" holds for the whole payment
    lifecycle, not just the current HTTP request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        correlation_id = request.headers.get(HEADER_NAME) or new_id()
        set_correlation_id(correlation_id)
        response = self.get_response(request)
        response[HEADER_NAME] = get_correlation_id()
        return response


class RequestTimingMiddleware:
    """Dependency-free request-latency visibility: logs every request's
    duration at DEBUG, and promotes it to WARNING when it exceeds
    SLOW_REQUEST_THRESHOLD_MS - enough to spot a payment-provider call
    hanging or a slow DB query without standing up a metrics stack."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.threshold_ms = getattr(settings, 'SLOW_REQUEST_THRESHOLD_MS', 2000)

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        duration_ms = (time.monotonic() - started) * 1000

        log_fn = logger.warning if duration_ms > self.threshold_ms else logger.debug
        log_fn(
            '%s %s -> %s in %.1fms',
            request.method, request.path, response.status_code, duration_ms,
        )
        return response
