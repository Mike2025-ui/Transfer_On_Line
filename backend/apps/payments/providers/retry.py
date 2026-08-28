import logging
import time

import requests

logger = logging.getLogger(__name__)

RETRYABLE_HTTP_STATUSES = {502, 503, 504}


class RetryableHTTPError(Exception):
    """Raised for a response status that is worth retrying (502/503/504).
    Distinct from a provider's own business-error response (4xx), which
    must never be retried."""

    def __init__(self, response):
        self.response = response
        super().__init__(f'retryable HTTP status {response.status_code}')


def raise_if_retryable_status(response):
    if response.status_code in RETRYABLE_HTTP_STATUSES:
        raise RetryableHTTPError(response)


def call_with_retries(func, *, max_attempts, base_delay_seconds, retry_on):
    """Exponential backoff: base_delay, base_delay*2, base_delay*4, ...
    Only exceptions in `retry_on` trigger a retry; anything else propagates
    immediately. `max_attempts` bounds the total number of tries so a dead
    provider can never cause an unbounded retry loop."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return func()
        except retry_on as exc:
            if attempt >= max_attempts:
                logger.warning('Giving up after %s attempt(s): %s', attempt, exc)
                raise
            delay = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning('Attempt %s/%s failed (%s), retrying in %ss', attempt, max_attempts, exc, delay)
            time.sleep(delay)


# --- Policies -----------------------------------------------------------
#
# verify_payment() is a GET: repeating it any number of times is always
# safe, so it retries on every transient failure (connection error, timeout,
# 502/503/504).
#
# create_payment() is a POST that creates money movement on the provider's
# side: a Timeout or a 502/503/504 does NOT tell us whether the provider
# actually received and processed the request before failing to answer.
# Blindly retrying it could create two payments for one transaction. It is
# therefore only retried for requests.exceptions.ConnectionError, which by
# definition means the TCP connection itself was never established (DNS
# failure, connection refused, reset before any byte was sent) - the request
# provably never reached the provider. Anything more ambiguous (Timeout,
# 502/503/504) is surfaced immediately instead of retried; the payment is
# already recorded locally as 'pending' regardless, and
# PaymentService.reconcile_pending() resolves the ambiguity later with a
# safe, idempotent verify_payment() GET.

VERIFY_RETRYABLE_EXCEPTIONS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout, RetryableHTTPError)
CREATE_RETRYABLE_EXCEPTIONS = (requests.exceptions.ConnectionError,)


def call_verify_with_retries(func, *, max_attempts=4, base_delay_seconds=1):
    return call_with_retries(func, max_attempts=max_attempts, base_delay_seconds=base_delay_seconds, retry_on=VERIFY_RETRYABLE_EXCEPTIONS)


def call_create_with_retries(func, *, max_attempts=2, base_delay_seconds=1):
    return call_with_retries(func, max_attempts=max_attempts, base_delay_seconds=base_delay_seconds, retry_on=CREATE_RETRYABLE_EXCEPTIONS)
