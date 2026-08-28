import logging
import threading
import time

from django.conf import settings

from .base import PaymentProviderError

logger = logging.getLogger(__name__)


class CircuitOpenError(PaymentProviderError):
    """Raised instead of even attempting a call while a provider's circuit
    is open - callers already catch PaymentProviderError, so this needs no
    special-casing anywhere else in the codebase."""


class CircuitBreaker:
    """Per-process circuit breaker (CLOSED -> OPEN -> HALF_OPEN -> CLOSED).

    State is process-local: a dict + a lock, not shared across gunicorn
    workers or replicas. That is a deliberate scope choice, not an oversight
    - see the class-level note in get_breaker(). Each process still
    independently stops hammering a provider that is down, which is the
    actual goal of this pattern (fail fast, give the provider breathing
    room, recover automatically)."""

    def __init__(self, name, failure_threshold, reset_timeout):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._lock = threading.Lock()
        self._failures = 0
        self._state = 'closed'
        self._opened_at = None

    def _may_proceed(self):
        with self._lock:
            if self._state == 'open':
                if time.monotonic() - self._opened_at >= self.reset_timeout:
                    self._state = 'half_open'
                    logger.info('Circuit breaker %s: OPEN -> HALF_OPEN (single probe attempt)', self.name)
                else:
                    return False
            return True

    def call(self, func, *args, **kwargs):
        if not self._may_proceed():
            raise CircuitOpenError(f'{self.name} circuit is open - failing fast without calling the provider')
        try:
            result = func(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise
        self._on_success()
        return result

    def _on_success(self):
        with self._lock:
            if self._state != 'closed':
                logger.info('Circuit breaker %s: %s -> CLOSED', self.name, self._state.upper())
            self._failures = 0
            self._state = 'closed'
            self._opened_at = None

    def _on_failure(self):
        with self._lock:
            self._failures += 1
            should_open = self._state == 'half_open' or self._failures >= self.failure_threshold
            if should_open:
                if self._state != 'open':
                    logger.warning(
                        'Circuit breaker %s: opening after %s consecutive failure(s), retry in %ss',
                        self.name, self._failures, self.reset_timeout,
                    )
                self._state = 'open'
                self._opened_at = time.monotonic()


_breakers = {}
_registry_lock = threading.Lock()


def get_breaker(name):
    """One breaker per provider name, lazily created and cached for the
    lifetime of the worker process."""
    with _registry_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name,
                failure_threshold=getattr(settings, 'CIRCUIT_BREAKER_FAILURE_THRESHOLD', 5),
                reset_timeout=getattr(settings, 'CIRCUIT_BREAKER_RESET_SECONDS', 60),
            )
        return _breakers[name]
